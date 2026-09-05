use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    io::{BufRead, BufReader},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
};
use tauri::{Manager, State};
mod project;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[derive(Clone, Deserialize, Serialize)]
struct BackendInfo {
    port: u16,
    token: String,
}

#[derive(Deserialize)]
struct DesktopBootstrap {
    next_data_dir: Option<String>,
}

struct DesktopPaths {
    bootstrap_path: PathBuf,
    data_root: PathBuf,
}

fn resolve_desktop_paths(local_app_data: &Path, bootstrap_text: Option<&str>) -> DesktopPaths {
    let default_root = local_app_data.join("TopOptPilot");
    let bootstrap_path = default_root.join("desktop-bootstrap.json");
    let configured_root = bootstrap_text
        .and_then(|text| serde_json::from_str::<DesktopBootstrap>(text).ok())
        .and_then(|value| value.next_data_dir)
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from);
    DesktopPaths {
        bootstrap_path,
        data_root: configured_root.unwrap_or(default_root),
    }
}

struct BackendState(Arc<Mutex<Option<BackendInfo>>>);
struct ChildGuard(Mutex<Option<Child>>);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        if let Ok(mut value) = self.0.lock() {
            if let Some(child) = value.as_mut() {
                let _ = child.kill();
            }
        }
    }
}

const CHAT_IMAGE_MAX_BYTES: u64 = 10 * 1024 * 1024;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DroppedImageData {
    file_name: String,
    media_type: String,
    size_bytes: usize,
    data_base64: String,
    sha256: String,
}

fn image_media_type(bytes: &[u8]) -> Option<&'static str> {
    if bytes.starts_with(&[0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a]) {
        return Some("image/png");
    }
    if bytes.starts_with(&[0xff, 0xd8, 0xff]) {
        return Some("image/jpeg");
    }
    if bytes.len() >= 12 && &bytes[..4] == b"RIFF" && &bytes[8..12] == b"WEBP" {
        return Some("image/webp");
    }
    None
}

fn extension_media_type(path: &Path) -> Option<&'static str> {
    match path
        .extension()?
        .to_string_lossy()
        .to_ascii_lowercase()
        .as_str()
    {
        "png" => Some("image/png"),
        "jpg" | "jpeg" => Some("image/jpeg"),
        "webp" => Some("image/webp"),
        "svg" => Some("image/svg+xml"),
        "pdf" => Some("application/pdf"),
        "docx" => Some("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "xlsx" => Some("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "txt" | "md" => Some("text/plain"),
        "csv" => Some("text/csv"),
        _ => None,
    }
}

fn attachment_media_type(path: &Path, bytes: &[u8]) -> Option<&'static str> {
    let declared = extension_media_type(path)?;
    let matches = match declared {
        "image/png" | "image/jpeg" | "image/webp" => image_media_type(bytes) == Some(declared),
        "application/pdf" => bytes.starts_with(b"%PDF-"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        | "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" => {
            bytes.starts_with(b"PK\x03\x04")
                || bytes.starts_with(b"PK\x05\x06")
                || bytes.starts_with(b"PK\x07\x08")
        }
        "image/svg+xml" => String::from_utf8_lossy(&bytes[..bytes.len().min(4096)])
            .to_ascii_lowercase()
            .contains("<svg"),
        "text/plain" | "text/csv" => !bytes[..bytes.len().min(4096)].contains(&0),
        _ => false,
    };
    matches.then_some(declared)
}

fn read_dropped_image(path: &Path) -> Result<DroppedImageData, String> {
    let metadata = std::fs::metadata(path).map_err(|_| "无法读取拖入的附件文件".to_string())?;
    if !metadata.is_file() {
        return Err("拖入对象不是普通文件".to_string());
    }
    if metadata.len() > CHAT_IMAGE_MAX_BYTES {
        return Err("单个附件不能超过 10 MB".to_string());
    }
    let bytes = std::fs::read(path).map_err(|_| "无法读取拖入的附件文件".to_string())?;
    let media_type =
        attachment_media_type(path, &bytes).ok_or("附件格式不受支持，或文件内容与扩展名不一致")?;
    let sha256 = format!("{:x}", Sha256::digest(&bytes));
    Ok(DroppedImageData {
        file_name: path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("dropped-attachment")
            .to_string(),
        media_type: media_type.to_string(),
        size_bytes: bytes.len(),
        data_base64: BASE64_STANDARD.encode(bytes),
        sha256,
    })
}

#[tauri::command]
fn read_dropped_images(paths: Vec<String>) -> Result<Vec<DroppedImageData>, String> {
    if paths.is_empty() || paths.len() > 4 {
        return Err("每条消息最多上传 4 个附件".to_string());
    }
    paths
        .into_iter()
        .map(|value| read_dropped_image(Path::new(&value)))
        .collect()
}

#[tauri::command]
fn backend_info(state: State<'_, BackendState>) -> Option<BackendInfo> {
    state.0.lock().ok().and_then(|value| value.clone())
}

fn spawn_backend(
    app: &tauri::AppHandle,
) -> Result<(Child, Arc<Mutex<Option<BackendInfo>>>), String> {
    let state = Arc::new(Mutex::new(None));
    let mut command;
    if cfg!(debug_assertions) {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        command = Command::new("python");
        command
            .args(["-m", "topoptpilot_desktop.api.desktop_sidecar"])
            .current_dir(root)
            .env("TOPPILOT_PARENT_PID", std::process::id().to_string());
    } else {
        let resources = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?;
        let backend = resources.join("resources/bin/topoptpilot-backend.exe");
        let local_app_data = app
            .path()
            .local_data_dir()
            .map_err(|error| error.to_string())?;
        let default_paths = resolve_desktop_paths(&local_app_data, None);
        std::fs::create_dir_all(
            default_paths
                .bootstrap_path
                .parent()
                .ok_or("Desktop bootstrap parent is unavailable")?,
        )
        .map_err(|error| error.to_string())?;
        let bootstrap_text = std::fs::read_to_string(&default_paths.bootstrap_path).ok();
        let paths = resolve_desktop_paths(&local_app_data, bootstrap_text.as_deref());
        // A configured directory is selected only on the next launch. No data is migrated.
        std::fs::create_dir_all(&paths.data_root).map_err(|error| error.to_string())?;
        let bootstrap_path = paths.bootstrap_path;
        let data = paths.data_root;
        command = Command::new(backend);
        command
            .current_dir(&data)
            .env("TOPPILOT_PARENT_PID", std::process::id().to_string())
            .env("TOPPILOT_RESOURCE_ROOT", resources.join("resources"))
            .env("TOPPILOT_DATA_DIR", &data)
            .env("TOPOPTPILOT_DATA_DIR", &data)
            .env("TOPPILOT_BOOTSTRAP_PATH", bootstrap_path)
            .env("TOPPILOT_NODE", resources.join("resources/node/node.exe"))
            .env(
                "TOPPILOT_MATLAB_MCP",
                resources
                    .join("resources/vendor/matlab-mcp-server/matlab-mcp-server-windows-x64.exe"),
            );
    }
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000);
    let mut child = command
        .spawn()
        .map_err(|error| format!("Failed to start backend: {error}"))?;
    let stdout = child.stdout.take().ok_or("Backend stdout unavailable")?;
    let shared = state.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(raw) = line.strip_prefix("TOPPILOT_SIDECAR=") {
                if let Ok(value) = serde_json::from_str::<BackendInfo>(raw) {
                    if let Ok(mut slot) = shared.lock() {
                        *slot = Some(value);
                    }
                }
            }
        }
    });
    Ok((child, state))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let (child, state) = spawn_backend(app.handle())?;
            app.manage(BackendState(state));
            app.manage(project::PatchApprovalState::default());
            app.manage(ChildGuard(Mutex::new(Some(child))));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_info,
            read_dropped_images,
            project::project_pick_folder,
            project::project_open,
            project::project_list,
            project::project_list_summary,
            project::project_read,
            project::project_save,
            project::project_create,
            project::project_rename,
            project::project_search,
            project::patch_preview,
            project::patch_apply,
        ])
        .build(tauri::generate_context!())
        .expect("error while running TopOptPilot desktop")
        .run(|app, event| {
            // 退出应用时同步结束后台 sidecar 进程；Drop 不可靠，这里显式终止。
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app.try_state::<ChildGuard>() {
                    if let Ok(mut value) = state.0.lock() {
                        if let Some(child) = value.as_mut() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_paths_use_localappdata_topoptpilot_desktop_without_roaming_storage() {
        let local_app_data = PathBuf::from(r"C:\Users\test\AppData\Local");

        let paths = resolve_desktop_paths(&local_app_data, None);

        let expected_root = local_app_data.join("TopOptPilot");
        assert_eq!(
            paths.bootstrap_path,
            expected_root.join("desktop-bootstrap.json")
        );
        assert_eq!(paths.data_root, expected_root);
    }

    #[test]
    fn bootstrap_override_changes_only_the_next_launch_data_root() {
        let local_app_data = PathBuf::from(r"C:\Users\test\AppData\Local");
        let configured = r#"{"next_data_dir":"D:\\Topology Data"}"#;

        let paths = resolve_desktop_paths(&local_app_data, Some(configured));

        assert_eq!(
            paths.bootstrap_path,
            local_app_data
                .join("TopOptPilot")
                .join("desktop-bootstrap.json")
        );
        assert_eq!(paths.data_root, PathBuf::from(r"D:\Topology Data"));
    }

    #[test]
    fn blank_or_invalid_bootstrap_keeps_the_local_default() {
        let local_app_data = PathBuf::from(r"C:\Users\test\AppData\Local");
        let expected = local_app_data.join("TopOptPilot");

        assert_eq!(
            resolve_desktop_paths(&local_app_data, Some(r#"{"next_data_dir":"   "}"#)).data_root,
            expected
        );
        assert_eq!(
            resolve_desktop_paths(&local_app_data, Some("not-json")).data_root,
            expected
        );
    }

    #[test]
    fn image_type_detection_accepts_supported_magic_bytes() {
        assert_eq!(
            image_media_type(&[0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a]),
            Some("image/png")
        );
        assert_eq!(
            image_media_type(&[0xff, 0xd8, 0xff, 0x00]),
            Some("image/jpeg")
        );
        assert_eq!(image_media_type(b"RIFFxxxxWEBP"), Some("image/webp"));
        assert_eq!(image_media_type(b"not an image"), None);
    }

    #[test]
    fn attachment_reader_recognizes_documents_by_extension_and_content() {
        assert_eq!(
            attachment_media_type(std::path::Path::new("report.pdf"), b"%PDF-1.7"),
            Some("application/pdf")
        );
        assert_eq!(
            attachment_media_type(std::path::Path::new("notes.docx"), b"PK\x03\x04test"),
            Some("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        );
        assert_eq!(
            attachment_media_type(std::path::Path::new("values.xlsx"), b"PK\x03\x04test"),
            Some("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        );
        assert_eq!(
            attachment_media_type(std::path::Path::new("shape.svg"), b"<svg></svg>"),
            Some("image/svg+xml")
        );
        assert_eq!(
            attachment_media_type(std::path::Path::new("notes.txt"), b"plain text"),
            Some("text/plain")
        );
        assert!(attachment_media_type(std::path::Path::new("fake.pdf"), b"not pdf").is_none());
    }

    #[test]
    fn dropped_image_reader_rejects_directories_oversize_files_and_disguised_extensions() {
        let root =
            std::env::temp_dir().join(format!("topoptpilot-drop-test-{}", std::process::id()));
        std::fs::create_dir_all(&root).expect("create test directory");
        let directory_error = read_dropped_image(&root).expect_err("directory must be rejected");
        assert!(!directory_error.contains(&root.to_string_lossy().to_string()));

        let oversized = root.join("oversized.png");
        let oversized_file = std::fs::File::create(&oversized).expect("create oversized test file");
        oversized_file
            .set_len(CHAT_IMAGE_MAX_BYTES + 1)
            .expect("create sparse oversized file");
        drop(oversized_file);
        assert!(read_dropped_image(&oversized)
            .expect_err("oversized file must be rejected")
            .contains("10 MB"));

        let disguised = root.join("disguised.jpg");
        std::fs::write(&disguised, [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a])
            .expect("write disguised image");
        assert!(read_dropped_image(&disguised)
            .expect_err("extension mismatch must be rejected")
            .contains("扩展名"));

        std::fs::remove_file(oversized).expect("remove oversized test file");
        std::fs::remove_file(disguised).expect("remove disguised test file");
        std::fs::remove_dir(root).expect("remove test directory");
    }
}
