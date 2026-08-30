use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, HashSet},
    fs,
    io::{Read, Seek, SeekFrom, Write},
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex, Weak},
    time::{Duration, Instant},
};
use tauri::State;

const ALLOWED_EXTENSIONS: &[&str] = &["m", "json", "md", "txt", "log", "csv"];
const PATCH_APPROVAL_TTL: Duration = Duration::from_secs(120);

const MAX_PATCH_APPROVALS: usize = 256;
#[derive(Debug, Serialize, Deserialize)]
pub struct ProjectEntry {
    pub relative_path: String,
    pub kind: String,
    pub size_bytes: u64,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct FilePayload {
    pub relative_path: String,
    pub content: String,
    pub sha256: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PatchFile {
    pub relative_path: String,
    pub before_digest: String,
    pub unified_diff: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PatchProposal {
    pub project_id: String,
    pub base_digest: String,
    pub files: Vec<PatchFile>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PatchPreviewResult {
    pub approval_token: String,
    pub proposal: PatchProposal,
}

struct PatchApproval {
    canonical_root: PathBuf,
    project_id: String,
    base_digest: String,
    proposal_digest: String,
    expires_at: Instant,
}

type ApprovalClock = Arc<dyn Fn() -> Instant + Send + Sync>;

pub struct PatchApprovalState {
    approvals: Mutex<HashMap<String, PatchApproval>>,
    transaction_locks: Mutex<HashMap<PathBuf, Weak<Mutex<()>>>>,
    ttl: Duration,
    max_approvals: usize,
    clock: ApprovalClock,
}

impl Default for PatchApprovalState {
    fn default() -> Self {
        Self {
            approvals: Mutex::new(HashMap::new()),
            transaction_locks: Mutex::new(HashMap::new()),
            ttl: PATCH_APPROVAL_TTL,
            max_approvals: MAX_PATCH_APPROVALS,
            clock: Arc::new(Instant::now),
        }
    }
}

impl PatchApprovalState {
    #[cfg(test)]
    fn with_clock(ttl: Duration, clock: impl Fn() -> Instant + Send + Sync + 'static) -> Self {
        Self::with_limits(ttl, MAX_PATCH_APPROVALS, clock)
    }

    #[cfg(test)]
    fn with_limits(
        ttl: Duration,
        max_approvals: usize,
        clock: impl Fn() -> Instant + Send + Sync + 'static,
    ) -> Self {
        Self {
            approvals: Mutex::new(HashMap::new()),
            transaction_locks: Mutex::new(HashMap::new()),
            ttl,
            max_approvals,
            clock: Arc::new(clock),
        }
    }

    fn transaction_lock(&self, canonical_root: &Path) -> Result<Arc<Mutex<()>>, String> {
        let mut locks = self
            .transaction_locks
            .lock()
            .map_err(|_| "patch transaction lock state is unavailable".to_string())?;
        locks.retain(|_, lock| lock.strong_count() > 0);
        if let Some(lock) = locks.get(canonical_root).and_then(Weak::upgrade) {
            return Ok(lock);
        }
        let lock = Arc::new(Mutex::new(()));
        locks.insert(canonical_root.to_path_buf(), Arc::downgrade(&lock));
        Ok(lock)
    }
}

fn allowed(path: &Path) -> bool {
    path.extension()
        .and_then(|v| v.to_str())
        .map(|ext| {
            ALLOWED_EXTENSIONS
                .iter()
                .any(|item| item.eq_ignore_ascii_case(ext))
        })
        .unwrap_or(false)
}
fn clean_relative(relative: &str) -> Result<PathBuf, String> {
    let path = Path::new(relative);
    if path.is_absolute() || relative.contains('\\') {
        return Err("relative path must use forward slashes".into());
    }
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::Normal(name) => normalized.push(name),
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err("path escapes project root".into());
            }
        }
    }
    if normalized.as_os_str().is_empty() || !allowed(&normalized) {
        return Err("file extension is not allowed".into());
    }
    Ok(normalized)
}
fn root_path(root: &str) -> Result<PathBuf, String> {
    let path = PathBuf::from(root);
    if !path.is_dir() {
        return Err("project root does not exist".into());
    }
    fs::canonicalize(path).map_err(|error| format!("project root unavailable: {error}"))
}
fn reject_symlink_components(root: &Path, candidate: &Path) -> Result<(), String> {
    let relative = candidate
        .strip_prefix(root)
        .map_err(|_| "path escapes project root".to_string())?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        let Component::Normal(name) = component else {
            continue;
        };
        current.push(name);
        match fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err("symbolic links are not allowed in project paths".into());
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(())
}

fn safe_file(root: &Path, relative: &str, allow_missing: bool) -> Result<PathBuf, String> {
    let clean = clean_relative(relative)?;
    let candidate = root.join(clean);
    reject_symlink_components(root, &candidate)?;
    if candidate.exists() {
        let metadata = fs::symlink_metadata(&candidate).map_err(|error| error.to_string())?;
        if metadata.file_type().is_symlink() {
            return Err("symbolic links are not allowed in project paths".into());
        }
        let canonical = fs::canonicalize(&candidate).map_err(|error| error.to_string())?;
        if !canonical.starts_with(root) {
            return Err("symbolic link escapes project root".into());
        }
        if canonical.is_dir() {
            return Err("expected a file".into());
        }
        Ok(canonical)
    } else if allow_missing {
        let parent = candidate.parent().ok_or("project file parent is missing")?;
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        reject_symlink_components(root, &candidate)?;
        let canonical_parent = fs::canonicalize(parent).map_err(|error| error.to_string())?;
        if !canonical_parent.starts_with(root) {
            return Err("symbolic link escapes project root".into());
        }
        let name = candidate
            .file_name()
            .ok_or("project file name is missing")?;
        Ok(canonical_parent.join(name))
    } else {
        Err("file does not exist".into())
    }
}

fn digest(content: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content);
    format!("{:x}", hasher.finalize())
}

fn project_id_for_root(canonical: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"topoptpilot-project-id-v1");
    hash_field(&mut hasher, canonical.to_string_lossy().as_bytes());
    format!("{:x}", hasher.finalize())
}

fn hash_field(hasher: &mut Sha256, value: &[u8]) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value);
}

fn proposal_base_digest(files: &[PatchFile]) -> String {
    if files.len() == 1 {
        return files[0].before_digest.clone();
    }
    let mut hasher = Sha256::new();
    hasher.update(b"topoptpilot-patch-baseline-v1");
    hasher.update((files.len() as u64).to_be_bytes());
    for file in files {
        hash_field(&mut hasher, file.relative_path.as_bytes());
        hash_field(&mut hasher, file.before_digest.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn proposal_digest(canonical: &Path, proposal: &PatchProposal) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"topoptpilot-patch-proposal-v1");
    hash_field(&mut hasher, canonical.to_string_lossy().as_bytes());
    hash_field(&mut hasher, proposal.project_id.as_bytes());
    hash_field(&mut hasher, proposal.base_digest.as_bytes());
    hasher.update((proposal.files.len() as u64).to_be_bytes());
    for file in &proposal.files {
        hash_field(&mut hasher, file.relative_path.as_bytes());
        hash_field(&mut hasher, file.before_digest.as_bytes());
        hash_field(&mut hasher, file.unified_diff.as_bytes());
    }
    format!("{:x}", hasher.finalize())
}

fn random_approval_token() -> Result<String, String> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut bytes = [0_u8; 32];
    getrandom::getrandom(&mut bytes)
        .map_err(|error| format!("approval token generation failed: {error}"))?;
    let mut token = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        token.push(HEX[(byte >> 4) as usize] as char);
        token.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(token)
}

fn target_identity(canonical_root: &Path, relative: &str) -> Result<String, String> {
    let target = safe_file(canonical_root, relative, false)?;
    let value = target.to_string_lossy().replace('\\', "/");
    #[cfg(windows)]
    {
        return Ok(value.to_lowercase());
    }
    #[cfg(not(windows))]
    Ok(value)
}

fn validate_proposal_identity(canonical: &Path, proposal: &PatchProposal) -> Result<(), String> {
    if proposal.files.is_empty() {
        return Err("patch proposal has no files".into());
    }
    if proposal.project_id != project_id_for_root(canonical) {
        return Err("patch projectId does not match the canonical project root".into());
    }
    if proposal.base_digest != proposal_base_digest(&proposal.files) {
        return Err("patch baseDigest does not match the ordered file baseline set".into());
    }
    let mut paths = HashSet::new();
    for file in &proposal.files {
        let identity = target_identity(canonical, &file.relative_path)?;
        if !paths.insert(identity) {
            return Err(format!(
                "patch proposal contains duplicate file: {}",
                file.relative_path
            ));
        }
    }
    Ok(())
}

fn canonical_picked_project(path: Option<PathBuf>) -> Result<Option<String>, String> {
    path.map(|selected| {
        let raw = selected
            .to_str()
            .ok_or_else(|| "selected project path is not valid Unicode".to_string())?;
        root_path(raw).map(|canonical| canonical.to_string_lossy().into_owned())
    })
    .transpose()
}

#[tauri::command]
pub async fn project_pick_folder() -> Result<Option<String>, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("选择或创建 TopOptPilot 项目文件夹")
        .pick_folder()
        .await
        .map(|handle| handle.path().to_path_buf());
    canonical_picked_project(selected)
}
#[tauri::command]
pub fn project_open(root: String) -> Result<serde_json::Value, String> {
    let canonical = root_path(&root)?;
    Ok(serde_json::json!({"root": canonical, "projectId": project_id_for_root(&canonical)}))
}
#[tauri::command]
pub fn project_list(root: String) -> Result<Vec<ProjectEntry>, String> {
    let canonical = root_path(&root)?;
    let mut entries = Vec::new();
    list_dir(&canonical, &canonical, &mut entries)?;
    Ok(entries)
}
fn list_dir(root: &Path, dir: &Path, entries: &mut Vec<ProjectEntry>) -> Result<(), String> {
    for item in fs::read_dir(dir).map_err(|e| e.to_string())? {
        let item = item.map_err(|e| e.to_string())?;
        let path = item.path();
        let metadata = fs::symlink_metadata(&path).map_err(|e| e.to_string())?;
        if metadata.file_type().is_symlink() {
            return Err("symbolic links are not allowed in project trees".into());
        }
        let rel = path
            .strip_prefix(root)
            .map_err(|e| e.to_string())?
            .to_string_lossy()
            .replace('\\', "/");
        if metadata.is_dir() {
            list_dir(root, &path, entries)?;
        } else if allowed(&path) {
            entries.push(ProjectEntry {
                relative_path: rel,
                kind: "file".into(),
                size_bytes: metadata.len(),
            });
        }
    }
    Ok(())
}
#[tauri::command]
pub fn project_read(root: String, relative_path: String) -> Result<FilePayload, String> {
    let canonical = root_path(&root)?;
    let path = safe_file(&canonical, &relative_path, false)?;
    let bytes = fs::read(&path).map_err(|e| e.to_string())?;
    let content =
        String::from_utf8(bytes.clone()).map_err(|_| "file is not valid UTF-8".to_string())?;
    Ok(FilePayload {
        relative_path,
        content,
        sha256: digest(&bytes),
    })
}
fn open_cas_read(path: &Path) -> Result<(fs::File, Vec<u8>), String> {
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // Permit readers and our atomic replacement, but deny newly opened write handles.
        // Windows cannot revoke a writer opened before this guard; the second digest check
        // below detects such writes up to the final atomic rename boundary.
        options.share_mode(0x0000_0001 | 0x0000_0004);
    }
    let mut file = options.open(path).map_err(|error| error.to_string())?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    Ok((file, bytes))
}

fn create_unique_temp_file(path: &Path) -> Result<(PathBuf, fs::File), String> {
    let parent = path.parent().ok_or("project file parent is missing")?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or("project file name is invalid")?;
    for _ in 0..8 {
        let token = random_approval_token()?;
        let temp = parent.join(format!(".{name}.tmp-{token}"));
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)
        {
            Ok(file) => return Ok((temp, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.to_string()),
        }
    }
    Err("could not allocate a unique temporary save file".into())
}

fn cas_digest(file: &mut fs::File) -> Result<String, String> {
    file.seek(SeekFrom::Start(0))
        .map_err(|error| error.to_string())?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    Ok(digest(&bytes))
}

fn project_save_with_io_hooks<W, S, H>(
    root: String,
    relative_path: String,
    content: String,
    expected_sha256: Option<String>,
    write_temp: W,
    sync_temp: S,
    pre_rename_hook: H,
) -> Result<FilePayload, String>
where
    W: FnOnce(&mut fs::File, &[u8]) -> Result<(), String>,
    S: FnOnce(&mut fs::File) -> Result<(), String>,
    H: FnOnce(&Path),
{
    let canonical = root_path(&root)?;
    let path = safe_file(&canonical, &relative_path, true)?;
    let mut cas_guard = None;
    if let Some(expected) = expected_sha256 {
        if path.exists() {
            let (file, current) = open_cas_read(&path)?;
            if digest(&current) != expected {
                return Err("file changed externally; reload before saving".into());
            }
            cas_guard = Some((file, expected));
        }
    }
    let bytes = content.as_bytes();
    std::str::from_utf8(bytes).map_err(|_| "content must be UTF-8")?;
    let sha256 = digest(bytes);
    let (temp, mut file) = create_unique_temp_file(&path)?;
    let io_result = write_temp(&mut file, bytes).and_then(|_| sync_temp(&mut file));
    drop(file);
    if let Err(error) = io_result {
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    if let Some((guarded, expected)) = cas_guard.as_mut() {
        if cas_digest(guarded)? != *expected {
            let _ = fs::remove_file(&temp);
            return Err("file changed externally during save; reload before saving".into());
        }
    }
    pre_rename_hook(&path);
    let rename_result = fs::rename(&temp, &path);
    drop(cas_guard);
    if let Err(error) = rename_result {
        let _ = fs::remove_file(&temp);
        return Err(error.to_string());
    }
    Ok(FilePayload {
        relative_path,
        content,
        sha256,
    })
}

fn project_save_with_pre_rename_hook<F>(
    root: String,
    relative_path: String,
    content: String,
    expected_sha256: Option<String>,
    pre_rename_hook: F,
) -> Result<FilePayload, String>
where
    F: FnOnce(&Path),
{
    project_save_with_io_hooks(
        root,
        relative_path,
        content,
        expected_sha256,
        |file, bytes| file.write_all(bytes).map_err(|error| error.to_string()),
        |file| file.sync_all().map_err(|error| error.to_string()),
        pre_rename_hook,
    )
}

#[tauri::command]
pub fn project_save(
    root: String,
    relative_path: String,
    content: String,
    expected_sha256: Option<String>,
) -> Result<FilePayload, String> {
    project_save_with_pre_rename_hook(root, relative_path, content, expected_sha256, |_| {})
}
#[tauri::command]
pub fn project_create(
    root: String,
    relative_path: String,
    content: Option<String>,
) -> Result<FilePayload, String> {
    let canonical = root_path(&root)?;
    let path = safe_file(&canonical, &relative_path, true)?;
    if path.exists() {
        return Err("file already exists".into());
    }
    project_save(root, relative_path, content.unwrap_or_default(), None)
}
#[tauri::command]
pub fn project_rename(root: String, from: String, to: String) -> Result<(), String> {
    let canonical = root_path(&root)?;
    let source = safe_file(&canonical, &from, false)?;
    let target = safe_file(&canonical, &to, true)?;
    if target.exists() {
        return Err("target already exists".into());
    }
    fs::rename(source, target).map_err(|e| e.to_string())
}
#[tauri::command]
pub fn project_search(root: String, query: String) -> Result<Vec<ProjectEntry>, String> {
    let entries = project_list(root)?;
    Ok(entries
        .into_iter()
        .filter(|entry| {
            entry
                .relative_path
                .to_lowercase()
                .contains(&query.to_lowercase())
        })
        .collect())
}

fn validate_patch(root: &str, canonical: &Path, proposal: &PatchProposal) -> Result<(), String> {
    validate_proposal_identity(canonical, proposal)?;
    for file in &proposal.files {
        let current = project_read(root.to_owned(), file.relative_path.clone())?;
        if current.sha256 != file.before_digest {
            return Err(format!("patch base conflict: {}", file.relative_path));
        }
        apply_unified_diff(&current.content, &file.unified_diff)?;
    }
    Ok(())
}

#[tauri::command]
pub fn patch_preview(
    state: State<'_, PatchApprovalState>,
    root: String,
    proposal: PatchProposal,
) -> Result<PatchPreviewResult, String> {
    patch_preview_with_state(state.inner(), root, proposal)
}

fn patch_preview_with_state(
    state: &PatchApprovalState,
    root: String,
    proposal: PatchProposal,
) -> Result<PatchPreviewResult, String> {
    let canonical = root_path(&root)?;
    let canonical_root = canonical.to_string_lossy().into_owned();
    validate_patch(&canonical_root, &canonical, &proposal)?;
    let now = (state.clock)();
    let mut approvals = state
        .approvals
        .lock()
        .map_err(|_| "patch approval state is unavailable".to_string())?;
    approvals.retain(|_, approval| approval.expires_at > now);
    if approvals.len() >= state.max_approvals {
        return Err(
            "patch approval capacity reached; wait for existing approvals to expire".into(),
        );
    }
    let token = loop {
        let candidate = random_approval_token()?;
        if !approvals.contains_key(&candidate) {
            break candidate;
        }
    };
    approvals.insert(
        token.clone(),
        PatchApproval {
            canonical_root: canonical,
            project_id: proposal.project_id.clone(),
            base_digest: proposal.base_digest.clone(),
            proposal_digest: proposal_digest(Path::new(&canonical_root), &proposal),
            expires_at: now + state.ttl,
        },
    );
    Ok(PatchPreviewResult {
        approval_token: token,
        proposal,
    })
}

fn consume_approval(
    state: &PatchApprovalState,
    approval_token: &str,
) -> Result<PatchApproval, String> {
    if approval_token.trim().is_empty() {
        return Err("approvalToken is required".into());
    }
    let mut approvals = state
        .approvals
        .lock()
        .map_err(|_| "patch approval state is unavailable".to_string())?;
    let now = (state.clock)();
    let approval = approvals.remove(approval_token);
    approvals.retain(|_, approval| approval.expires_at > now);
    let approval = approval.ok_or("approval token is unknown or already used")?;
    if approval.expires_at <= now {
        return Err("approval token has expired".into());
    }
    Ok(approval)
}
fn parse_hunk_range(token: &str, prefix: char) -> Result<(usize, usize), String> {
    let value = token
        .strip_prefix(prefix)
        .ok_or("invalid unified diff range")?;
    let mut parts = value.splitn(2, ',');
    let start = parts
        .next()
        .and_then(|item| item.parse::<usize>().ok())
        .ok_or("invalid unified diff start")?;
    let count = parts
        .next()
        .map(|item| item.parse::<usize>().ok())
        .flatten()
        .unwrap_or(1);
    Ok((start, count))
}

fn apply_unified_diff(original: &str, diff: &str) -> Result<String, String> {
    if diff.trim().is_empty() {
        return Err("patch diff is empty".into());
    }
    let line_ending = if original.contains("\r\n") {
        "\r\n"
    } else {
        "\n"
    };
    let original_has_newline = original.ends_with('\n');
    let mut original_lines: Vec<String> = original
        .split('\n')
        .map(|line| line.strip_suffix('\r').unwrap_or(line).to_string())
        .collect();
    if original_has_newline {
        original_lines.pop();
    }
    let lines: Vec<&str> = diff.lines().collect();
    let mut result = Vec::new();
    let mut cursor = 0usize;
    let mut index = 0usize;
    let mut saw_hunk = false;
    let mut no_newline_at_end = false;

    while index < lines.len() {
        let line = lines[index];
        if line.starts_with("---") || line.starts_with("+++") {
            index += 1;
            continue;
        }
        if !line.starts_with("@@") {
            return Err("patch must contain unified diff headers".into());
        }
        let header_end = line[2..]
            .find("@@")
            .ok_or("invalid unified diff hunk header")?
            + 2;
        let mut header_parts = line[2..header_end].split_whitespace();
        let (old_start, old_count) =
            parse_hunk_range(header_parts.next().ok_or("missing old range")?, '-')?;
        let (_new_start, new_count) =
            parse_hunk_range(header_parts.next().ok_or("missing new range")?, '+')?;
        let target = if old_start == 0 { 0 } else { old_start - 1 };
        if target < cursor || target > original_lines.len() {
            return Err("unified diff hunk is outside the original file".into());
        }
        while cursor < target {
            result.push(original_lines[cursor].clone());
            cursor += 1;
        }
        let mut old_seen = 0usize;
        let mut new_seen = 0usize;
        saw_hunk = true;
        index += 1;
        while index < lines.len() && !lines[index].starts_with("@@") {
            let hunk_line = lines[index];
            if hunk_line == r"\ No newline at end of file" {
                no_newline_at_end = true;
                index += 1;
                continue;
            }
            if hunk_line.is_empty() {
                return Err("invalid empty unified diff line".into());
            }
            let (kind, value) = hunk_line.split_at(1);
            match kind {
                " " => {
                    if cursor >= original_lines.len() || original_lines[cursor] != value {
                        return Err("unified diff context does not match the original file".into());
                    }
                    result.push(value.to_string());
                    cursor += 1;
                    old_seen += 1;
                    new_seen += 1;
                }
                "-" => {
                    if cursor >= original_lines.len() || original_lines[cursor] != value {
                        return Err("unified diff deletion does not match the original file".into());
                    }
                    cursor += 1;
                    old_seen += 1;
                }
                "+" => {
                    result.push(value.to_string());
                    new_seen += 1;
                }
                _ => return Err("invalid unified diff line prefix".into()),
            }
            index += 1;
        }
        if old_seen != old_count || new_seen != new_count {
            return Err("unified diff hunk line counts do not match".into());
        }
    }
    if !saw_hunk {
        return Err("patch must contain a unified diff hunk".into());
    }
    while cursor < original_lines.len() {
        result.push(original_lines[cursor].clone());
        cursor += 1;
    }
    let mut output = result.join(line_ending);
    if original_has_newline && !no_newline_at_end {
        output.push_str(line_ending);
    }
    Ok(output)
}

#[tauri::command]
pub fn patch_apply(
    state: State<'_, PatchApprovalState>,
    root: String,
    proposal: PatchProposal,
    approval_token: String,
) -> Result<Vec<FilePayload>, String> {
    patch_apply_with_state(state.inner(), root, proposal, approval_token)
}

fn patch_apply_with_state(
    state: &PatchApprovalState,
    root: String,
    proposal: PatchProposal,
    approval_token: String,
) -> Result<Vec<FilePayload>, String> {
    let approval = consume_approval(state, &approval_token)?;
    let canonical = root_path(&root)?;
    if canonical != approval.canonical_root {
        return Err("approval token was issued for a different project root".into());
    }
    if proposal.project_id != approval.project_id {
        return Err("approval token projectId mismatch".into());
    }
    if proposal.base_digest != approval.base_digest {
        return Err("approval token baseDigest mismatch".into());
    }
    if proposal_digest(&canonical, &proposal) != approval.proposal_digest {
        return Err("approval token proposal mismatch".into());
    }
    let transaction_lock = state.transaction_lock(&canonical)?;
    let _transaction = transaction_lock
        .lock()
        .map_err(|_| "patch transaction lock is unavailable".to_string())?;
    let canonical_root = canonical.to_string_lossy().into_owned();
    validate_patch(&canonical_root, &canonical, &proposal)?;
    apply_patch_transaction(canonical_root, proposal)
}

fn apply_patch_transaction(
    root: String,
    proposal: PatchProposal,
) -> Result<Vec<FilePayload>, String> {
    apply_patch_transaction_with_save(root, proposal, project_save)
}

fn apply_patch_transaction_with_save<F>(
    root: String,
    proposal: PatchProposal,
    mut save: F,
) -> Result<Vec<FilePayload>, String>
where
    F: FnMut(String, String, String, Option<String>) -> Result<FilePayload, String>,
{
    let mut pending = Vec::new();
    for file in proposal.files {
        let current = project_read(root.clone(), file.relative_path.clone())?;
        if current.sha256 != file.before_digest {
            return Err(format!("patch base conflict: {}", file.relative_path));
        }
        let content = apply_unified_diff(&current.content, &file.unified_diff)?;
        pending.push((file.relative_path, current, content));
    }

    let mut applied: Vec<(String, FilePayload, String)> = Vec::new();
    let mut outputs = Vec::new();
    for (relative_path, original, content) in pending {
        match save(
            root.clone(),
            relative_path.clone(),
            content.clone(),
            Some(original.sha256.clone()),
        ) {
            Ok(payload) => {
                applied.push((relative_path, original, payload.sha256.clone()));
                outputs.push(payload);
            }
            Err(error) => {
                let mut rollback_failures = Vec::new();
                for (path, previous, new_digest) in applied.iter().rev() {
                    if save(
                        root.clone(),
                        path.clone(),
                        previous.content.clone(),
                        Some(new_digest.clone()),
                    )
                    .is_err()
                    {
                        rollback_failures.push(path.clone());
                    }
                }
                if !rollback_failures.is_empty() {
                    return Err(format!(
                        "PARTIAL_APPLY: patch transaction failed: {error}; rollback failed for: {}",
                        rollback_failures.join(", ")
                    ));
                }
                return Err(format!("patch transaction failed: {error}"));
            }
        }
    }
    Ok(outputs)
}

#[cfg(test)]
mod tests {
    use super::{
        apply_patch_transaction, apply_patch_transaction_with_save, apply_unified_diff,
        canonical_picked_project, clean_relative, create_unique_temp_file, digest,
        patch_apply_with_state, patch_preview_with_state, project_id_for_root,
        proposal_base_digest, safe_file, PatchApprovalState, PatchFile, PatchProposal,
    };
    use std::{
        fs,
        io::Write,
        sync::{Arc, Barrier, Mutex},
        thread,
        time::{Duration, Instant},
    };

    #[test]
    fn picked_project_is_cancel_safe_and_canonicalizes_only_directories() {
        assert_eq!(canonical_picked_project(None).unwrap(), None);
        let base =
            std::env::temp_dir().join(format!("topoptpilot-folder-picker-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        let selected = canonical_picked_project(Some(base.clone()))
            .unwrap()
            .unwrap();
        assert_eq!(selected, fs::canonicalize(&base).unwrap().to_string_lossy());
        let file = base.join("not-a-folder.m");
        fs::write(&file, "x").unwrap();
        assert!(canonical_picked_project(Some(file)).is_err());
        let _ = fs::remove_dir_all(base);
    }
    fn patch_fixture(name: &str) -> (std::path::PathBuf, String, PatchProposal) {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        let sequence = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let base = std::env::temp_dir().join(format!(
            "topoptpilot-approval-{name}-{}-{sequence}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        fs::write(base.join("solver.m"), "alpha\nbeta\n").unwrap();
        let canonical = fs::canonicalize(&base).unwrap();
        let root = canonical.to_string_lossy().into_owned();
        let before_digest = digest(b"alpha\nbeta\n");
        let proposal = PatchProposal {
            project_id: project_id_for_root(&canonical),
            base_digest: before_digest.clone(),
            files: vec![PatchFile {
                relative_path: "solver.m".into(),
                before_digest,
                unified_diff:
                    "--- a/solver.m\n+++ b/solver.m\n@@ -1,2 +1,2 @@\n alpha\n-beta\n+delta\n"
                        .into(),
            }],
        };
        (base, root, proposal)
    }

    #[test]
    fn rejects_parent_paths_and_unlisted_extensions() {
        assert!(clean_relative("../secret.txt").is_err());
        assert!(clean_relative("script.ps1").is_err());
        assert!(clean_relative("solver/main.m").is_ok());
    }

    #[test]
    fn computes_stable_sha256_for_patch_baselines() {
        assert_eq!(
            digest(b"TopOptPilot"),
            "7d690ab22d57dac4664aa7c25966ff3ed1f59d45d8f26cda0fe117474550a57a"
        );
    }

    #[test]
    fn unified_diff_applies_context_and_rejects_mismatch() {
        let original = "alpha\nbeta\ngamma\n";
        let diff = "--- a/file.m\n+++ b/file.m\n@@ -1,3 +1,3 @@\n alpha\n-beta\n+delta\n gamma\n";
        assert_eq!(
            apply_unified_diff(original, diff).unwrap(),
            "alpha\ndelta\ngamma\n"
        );

        let mismatch =
            "--- a/file.m\n+++ b/file.m\n@@ -1,3 +1,3 @@\n alpha\n-wrong\n+delta\n gamma\n";
        assert!(apply_unified_diff(original, mismatch).is_err());
    }

    #[test]
    fn patch_preview_validates_digest_and_context_without_writing() {
        let base = std::env::temp_dir().join(format!("topoptpilot-preview-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        let source = base.join("solver.m");
        fs::write(&source, "alpha\nbeta\n").unwrap();
        let canonical = fs::canonicalize(&base).unwrap();
        let proposal = PatchProposal {
            project_id: project_id_for_root(&canonical),
            base_digest: digest(b"alpha\nbeta\n"),
            files: vec![PatchFile {
                relative_path: "solver.m".into(),
                before_digest: digest(b"alpha\nbeta\n"),
                unified_diff: "@@ -1,2 +1,2 @@\n wrong\n-beta\n+delta\n".into(),
            }],
        };
        assert!(patch_preview_with_state(
            &PatchApprovalState::default(),
            base.to_string_lossy().into_owned(),
            proposal
        )
        .is_err());
        assert_eq!(fs::read_to_string(&source).unwrap(), "alpha\nbeta\n");
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn patch_apply_validates_all_files_before_writing() {
        let base = std::env::temp_dir().join(format!("topoptpilot-patch-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        let first = base.join("first.m");
        let second = base.join("second.m");
        std::fs::write(&first, "one\n").unwrap();
        std::fs::write(&second, "two\n").unwrap();
        let proposal = PatchProposal {
            project_id: "test".into(),
            base_digest: "test".into(),
            files: vec![
                PatchFile {
                    relative_path: "first.m".into(),
                    before_digest: digest(b"one\n"),
                    unified_diff: "--- a/first.m\n+++ b/first.m\n@@ -1,1 +1,1 @@\n-one\n+changed\n"
                        .into(),
                },
                PatchFile {
                    relative_path: "second.m".into(),
                    before_digest: digest(b"two\n"),
                    unified_diff:
                        "--- a/second.m\n+++ b/second.m\n@@ -1,1 +1,1 @@\n-wrong\n+changed\n".into(),
                },
            ],
        };
        let root = base.to_string_lossy().into_owned();
        assert!(apply_patch_transaction(root, proposal).is_err());
        assert_eq!(std::fs::read_to_string(&first).unwrap(), "one\n");
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn patch_apply_requires_a_preview_token() {
        let (base, root, proposal) = patch_fixture("without-preview");
        let state = PatchApprovalState::default();
        assert!(patch_apply_with_state(&state, root, proposal, String::new()).is_err());
        assert_eq!(
            fs::read_to_string(base.join("solver.m")).unwrap(),
            "alpha\nbeta\n"
        );
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn valid_preview_token_applies_once_and_cannot_be_reused() {
        let (base, root, proposal) = patch_fixture("valid-once");
        let state = PatchApprovalState::default();
        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        let applied = patch_apply_with_state(
            &state,
            root.clone(),
            proposal.clone(),
            preview.approval_token.clone(),
        )
        .unwrap();
        assert_eq!(applied[0].content, "alpha\ndelta\n");
        assert!(patch_apply_with_state(&state, root, proposal, preview.approval_token).is_err());
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn approval_tokens_are_unpredictable_per_preview() {
        let (base, root, proposal) = patch_fixture("random-token");
        let state = PatchApprovalState::default();
        let first = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        let second = patch_preview_with_state(&state, root, proposal).unwrap();
        assert_ne!(first.approval_token, second.approval_token);
        assert!(first.approval_token.len() >= 32);
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn approval_rejects_proposal_tampering() {
        let (base, root, proposal) = patch_fixture("proposal-tamper");
        let state = PatchApprovalState::default();
        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        let mut tampered = proposal;
        tampered.files[0].unified_diff =
            "--- a/solver.m\n+++ b/solver.m\n@@ -1,2 +1,2 @@\n alpha\n-beta\n+epsilon\n".into();
        assert!(patch_apply_with_state(&state, root, tampered, preview.approval_token).is_err());
        assert_eq!(
            fs::read_to_string(base.join("solver.m")).unwrap(),
            "alpha\nbeta\n"
        );
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn approval_binds_root_project_id_and_base_digest() {
        let (base, root, proposal) = patch_fixture("identity-binding");
        let other = base.with_extension("other");
        let _ = fs::remove_dir_all(&other);
        fs::create_dir_all(&other).unwrap();
        fs::write(other.join("solver.m"), "alpha\nbeta\n").unwrap();
        let other_root = fs::canonicalize(&other)
            .unwrap()
            .to_string_lossy()
            .into_owned();
        let state = PatchApprovalState::default();

        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        assert!(patch_apply_with_state(
            &state,
            other_root,
            proposal.clone(),
            preview.approval_token
        )
        .is_err());

        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        let mut wrong_project = proposal.clone();
        wrong_project.project_id = "0".repeat(64);
        assert!(patch_apply_with_state(
            &state,
            root.clone(),
            wrong_project,
            preview.approval_token
        )
        .is_err());

        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        let mut wrong_base = proposal;
        wrong_base.base_digest = "f".repeat(64);
        assert!(patch_apply_with_state(&state, root, wrong_base, preview.approval_token).is_err());

        let _ = fs::remove_dir_all(base);
        let _ = fs::remove_dir_all(other);
    }

    #[test]
    fn base_digest_is_single_digest_or_ordered_multi_file_baseline() {
        let first = PatchFile {
            relative_path: "a.m".into(),
            before_digest: "a".repeat(64),
            unified_diff: "unused".into(),
        };
        let second = PatchFile {
            relative_path: "b.m".into(),
            before_digest: "b".repeat(64),
            unified_diff: "unused".into(),
        };
        assert_eq!(proposal_base_digest(&[first.clone()]), first.before_digest);
        assert_ne!(
            proposal_base_digest(&[first.clone(), second.clone()]),
            proposal_base_digest(&[second, first])
        );
    }

    #[test]
    fn approval_rejects_reordered_files_with_recomputed_base_digest() {
        let (base, root, mut proposal) = patch_fixture("file-order");
        fs::write(base.join("second.m"), "alpha\nbeta\n").unwrap();
        proposal.files.push(PatchFile {
            relative_path: "second.m".into(),
            before_digest: digest(b"alpha\nbeta\n"),
            unified_diff:
                "--- a/second.m\n+++ b/second.m\n@@ -1,2 +1,2 @@\n alpha\n-beta\n+delta\n".into(),
        });
        proposal.base_digest = proposal_base_digest(&proposal.files);
        let state = PatchApprovalState::default();
        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        proposal.files.reverse();
        proposal.base_digest = proposal_base_digest(&proposal.files);
        assert!(patch_apply_with_state(&state, root, proposal, preview.approval_token).is_err());
        assert_eq!(
            fs::read_to_string(base.join("solver.m")).unwrap(),
            "alpha\nbeta\n"
        );
        assert_eq!(
            fs::read_to_string(base.join("second.m")).unwrap(),
            "alpha\nbeta\n"
        );
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn external_change_after_preview_fails_and_consumes_token() {
        let (base, root, proposal) = patch_fixture("external-change");
        let state = PatchApprovalState::default();
        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        fs::write(base.join("solver.m"), "externally changed\n").unwrap();
        assert!(patch_apply_with_state(
            &state,
            root.clone(),
            proposal.clone(),
            preview.approval_token.clone()
        )
        .is_err());
        fs::write(base.join("solver.m"), "alpha\nbeta\n").unwrap();
        assert!(patch_apply_with_state(&state, root, proposal, preview.approval_token).is_err());
        assert_eq!(
            fs::read_to_string(base.join("solver.m")).unwrap(),
            "alpha\nbeta\n"
        );
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn expired_approval_is_rejected_without_sleeping() {
        let (base, root, proposal) = patch_fixture("expired");
        let now = Arc::new(Mutex::new(Instant::now()));
        let clock = Arc::clone(&now);
        let state =
            PatchApprovalState::with_clock(Duration::from_secs(30), move || *clock.lock().unwrap());
        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        *now.lock().unwrap() += Duration::from_secs(31);
        assert!(patch_apply_with_state(&state, root, proposal, preview.approval_token).is_err());
        assert_eq!(
            fs::read_to_string(base.join("solver.m")).unwrap(),
            "alpha\nbeta\n"
        );
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn concurrent_approved_tokens_for_one_root_serialize_and_revalidate() {
        let (base, root, proposal) = patch_fixture("concurrent-root-lock");
        let state = Arc::new(PatchApprovalState::default());
        let first = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        let mut alternative = proposal.clone();
        alternative.files[0].unified_diff =
            "--- a/solver.m\n+++ b/solver.m\n@@ -1,2 +1,2 @@\n alpha\n-beta\n+epsilon\n".into();
        let second = patch_preview_with_state(&state, root.clone(), alternative.clone()).unwrap();
        let canonical = fs::canonicalize(&base).unwrap();
        let root_lock = state.transaction_lock(&canonical).unwrap();
        let held = root_lock.lock().unwrap();
        let start = Arc::new(Barrier::new(3));

        let first_state = Arc::clone(&state);
        let first_root = root.clone();
        let first_start = Arc::clone(&start);
        let first_thread = thread::spawn(move || {
            first_start.wait();
            patch_apply_with_state(&first_state, first_root, proposal, first.approval_token)
        });
        let second_state = Arc::clone(&state);
        let second_start = Arc::clone(&start);
        let second_thread = thread::spawn(move || {
            second_start.wait();
            patch_apply_with_state(&second_state, root, alternative, second.approval_token)
        });
        start.wait();
        drop(held);

        let results = [first_thread.join().unwrap(), second_thread.join().unwrap()];
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(results.iter().filter(|result| result.is_err()).count(), 1);
        let content = fs::read_to_string(base.join("solver.m")).unwrap();
        assert!(content == "alpha\ndelta\n" || content == "alpha\nepsilon\n");
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn external_change_waiting_on_root_lock_is_revalidated_inside_lock() {
        let (base, root, proposal) = patch_fixture("locked-external-change");
        let state = Arc::new(PatchApprovalState::default());
        let preview = patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        let canonical = fs::canonicalize(&base).unwrap();
        let root_lock = state.transaction_lock(&canonical).unwrap();
        let held = root_lock.lock().unwrap();
        let worker_state = Arc::clone(&state);
        let worker = thread::spawn(move || {
            patch_apply_with_state(&worker_state, root, proposal, preview.approval_token)
        });
        fs::write(base.join("solver.m"), "external\n").unwrap();
        drop(held);

        assert!(worker.join().unwrap().is_err());
        assert_eq!(
            fs::read_to_string(base.join("solver.m")).unwrap(),
            "external\n"
        );
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn rollback_failure_reports_partial_apply_paths() {
        let base =
            std::env::temp_dir().join(format!("topoptpilot-partial-apply-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        fs::write(base.join("first.m"), "one\n").unwrap();
        fs::write(base.join("second.m"), "two\n").unwrap();
        let root = fs::canonicalize(&base)
            .unwrap()
            .to_string_lossy()
            .into_owned();
        let files = vec![
            PatchFile {
                relative_path: "first.m".into(),
                before_digest: digest(b"one\n"),
                unified_diff: "@@ -1 +1 @@\n-one\n+changed-one\n".into(),
            },
            PatchFile {
                relative_path: "second.m".into(),
                before_digest: digest(b"two\n"),
                unified_diff: "@@ -1 +1 @@\n-two\n+changed-two\n".into(),
            },
        ];
        let proposal = PatchProposal {
            project_id: project_id_for_root(&fs::canonicalize(&base).unwrap()),
            base_digest: proposal_base_digest(&files),
            files,
        };
        let mut calls = 0;
        let error = apply_patch_transaction_with_save(root.clone(), proposal, |r, p, c, e| {
            calls += 1;
            match calls {
                1 => super::project_save(r, p, c, e),
                2 => Err("injected second write failure".into()),
                _ => Err("injected rollback failure".into()),
            }
        })
        .unwrap_err();

        assert!(error.contains("PARTIAL_APPLY"));
        assert!(error.contains("first.m"));
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn approval_capacity_is_bounded_and_expired_entries_are_pruned() {
        let (base, root, proposal) = patch_fixture("approval-capacity");
        let now = Arc::new(Mutex::new(Instant::now()));
        let clock = Arc::clone(&now);
        let state = PatchApprovalState::with_limits(Duration::from_secs(30), 2, move || {
            *clock.lock().unwrap()
        });
        patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        patch_preview_with_state(&state, root.clone(), proposal.clone()).unwrap();
        assert!(patch_preview_with_state(&state, root.clone(), proposal.clone()).is_err());
        *now.lock().unwrap() += Duration::from_secs(31);
        assert!(patch_preview_with_state(&state, root, proposal).is_ok());
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn project_id_is_domain_separated_and_stable() {
        let (base, _, _) = patch_fixture("project-id-domain");
        let canonical = fs::canonicalize(&base).unwrap();
        let id = project_id_for_root(&canonical);
        assert_eq!(id, project_id_for_root(&canonical));
        assert_ne!(id, digest(canonical.to_string_lossy().as_bytes()));
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn normalized_duplicate_paths_are_rejected() {
        let (base, root, mut proposal) = patch_fixture("normalized-duplicate");
        proposal.files.push(PatchFile {
            relative_path: "./solver.m".into(),
            before_digest: digest(b"alpha\nbeta\n"),
            unified_diff: proposal.files[0].unified_diff.clone(),
        });
        proposal.base_digest = proposal_base_digest(&proposal.files);
        assert!(patch_preview_with_state(&PatchApprovalState::default(), root, proposal).is_err());
        let _ = fs::remove_dir_all(base);
    }

    #[cfg(windows)]
    #[test]
    fn windows_equivalent_target_paths_are_rejected() {
        let (base, root, mut proposal) = patch_fixture("windows-equivalent-target");
        proposal.files.push(PatchFile {
            relative_path: "SOLVER.m".into(),
            before_digest: digest(b"alpha\nbeta\n"),
            unified_diff: proposal.files[0].unified_diff.clone(),
        });
        proposal.base_digest = proposal_base_digest(&proposal.files);

        assert!(patch_preview_with_state(&PatchApprovalState::default(), root, proposal).is_err());
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn temporary_save_files_use_unique_random_names() {
        let base = std::env::temp_dir().join(format!("topoptpilot-temp-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        let target = base.join("solver.m");
        let (first_path, first_file) = create_unique_temp_file(&target).unwrap();
        drop(first_file);
        let (second_path, second_file) = create_unique_temp_file(&target).unwrap();
        drop(second_file);
        assert_ne!(first_path, second_path);
        assert!(!first_path
            .to_string_lossy()
            .ends_with(&std::process::id().to_string()));
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn project_save_atomically_replaces_an_existing_file() {
        let base =
            std::env::temp_dir().join(format!("topoptpilot-save-existing-{}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        let source = base.join("solver.m");
        fs::write(&source, "before\n").unwrap();

        let saved = super::project_save(
            base.to_string_lossy().into_owned(),
            "solver.m".into(),
            "after\n".into(),
            Some(digest(b"before\n")),
        )
        .unwrap();
        assert_eq!(saved.content, "after\n");
        assert_eq!(fs::read_to_string(&source).unwrap(), "after\n");
        let _ = fs::remove_dir_all(&base);
    }

    #[cfg(windows)]
    #[test]
    fn project_save_keeps_cas_guard_alive_through_atomic_rename() {
        let base = std::env::temp_dir().join(format!(
            "topoptpilot-save-guard-lifetime-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        let source = base.join("solver.m");
        fs::write(&source, "before\n").unwrap();

        let saved = super::project_save_with_pre_rename_hook(
            base.to_string_lossy().into_owned(),
            "solver.m".into(),
            "after\n".into(),
            Some(digest(b"before\n")),
            |target| {
                assert!(fs::OpenOptions::new().write(true).open(target).is_err());
                assert_eq!(fs::read_to_string(target).unwrap(), "before\n");
            },
        )
        .unwrap();

        assert_eq!(saved.content, "after\n");
        assert_eq!(fs::read_to_string(&source).unwrap(), "after\n");
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn project_save_cleans_temp_files_after_write_and_sync_failures() {
        let base = std::env::temp_dir().join(format!(
            "topoptpilot-save-temp-cleanup-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        let source = base.join("solver.m");
        fs::write(&source, "before\n").unwrap();
        let root = base.to_string_lossy().into_owned();

        let write_error = super::project_save_with_io_hooks(
            root.clone(),
            "solver.m".into(),
            "after\n".into(),
            Some(digest(b"before\n")),
            |_, _| Err("injected temp write failure".into()),
            |file| file.sync_all().map_err(|error| error.to_string()),
            |_| {},
        )
        .unwrap_err();
        assert!(write_error.contains("injected temp write failure"));
        assert_eq!(fs::read_to_string(&source).unwrap(), "before\n");
        assert!(!fs::read_dir(&base).unwrap().any(|entry| {
            entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".solver.m.tmp-")
        }));

        let sync_error = super::project_save_with_io_hooks(
            root,
            "solver.m".into(),
            "after\n".into(),
            Some(digest(b"before\n")),
            |file, bytes| file.write_all(bytes).map_err(|error| error.to_string()),
            |_| Err("injected temp sync failure".into()),
            |_| {},
        )
        .unwrap_err();
        assert!(sync_error.contains("injected temp sync failure"));
        assert_eq!(fs::read_to_string(&source).unwrap(), "before\n");
        assert!(!fs::read_dir(&base).unwrap().any(|entry| {
            entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".solver.m.tmp-")
        }));
        let _ = fs::remove_dir_all(&base);
    }

    #[cfg(windows)]
    #[test]
    fn rejects_junctions_while_listing_project_trees() {
        let base =
            std::env::temp_dir().join(format!("topoptpilot-junction-{}", std::process::id()));
        let root = base.join("root");
        let outside = base.join("outside");
        let linked = root.join("linked");
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();
        fs::write(outside.join("outside.m"), "escaped\n").unwrap();

        let output = std::process::Command::new("cmd.exe")
            .args(["/C", "mklink", "/J"])
            .arg(&linked)
            .arg(&outside)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "failed to create junction: stdout={} stderr={}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );

        let canonical_root = fs::canonicalize(&root).unwrap();
        let mut entries = Vec::new();
        let error = super::list_dir(&canonical_root, &canonical_root, &mut entries).unwrap_err();
        assert_eq!(error, "symbolic links are not allowed in project trees");

        fs::remove_dir(&linked).unwrap();
        fs::remove_dir_all(&base).unwrap();
    }

    #[test]
    fn rejects_symlinked_parent_for_new_file() {
        let base = std::env::temp_dir().join(format!("topoptpilot-symlink-{}", std::process::id()));
        let root = base.join("root");
        let outside = base.join("outside");
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&outside).unwrap();

        #[cfg(windows)]
        {
            use std::os::windows::fs::symlink_dir;
            let linked = root.join("linked");
            if symlink_dir(&outside, &linked).is_err() {
                let _ = fs::remove_dir_all(&base);
                return;
            }
            assert!(safe_file(&root, "linked/new.m", true).is_err());
            let _ = fs::remove_file(&linked);
        }
        let _ = fs::remove_dir_all(&base);
    }
}
