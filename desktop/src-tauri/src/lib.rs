use serde::{Deserialize, Serialize};
use std::{
    io::{BufRead, BufReader},
    path::PathBuf,
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
            .args(["-m", "idesktop_v2.api.desktop_sidecar"])
            .current_dir(root);
    } else {
        let resources = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?;
        let backend = resources.join("resources/bin/topoptpilot-backend.exe");
        let app_data = app
            .path()
            .app_data_dir()
            .map_err(|error| error.to_string())?;
        std::fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
        let bootstrap_path = app_data.join("desktop-bootstrap.json");
        let configured_root = std::fs::read_to_string(&bootstrap_path)
            .ok()
            .and_then(|text| serde_json::from_str::<DesktopBootstrap>(&text).ok())
            .and_then(|value| value.next_data_dir)
            .filter(|value| !value.trim().is_empty())
            .map(PathBuf::from);
        // A configured directory is selected only on the next launch. No data is migrated.
        let data = configured_root.unwrap_or_else(|| app_data.join("storage"));
        std::fs::create_dir_all(&data).map_err(|error| error.to_string())?;
        command = Command::new(backend);
        command
            .current_dir(&data)
            .env("TOPPILOT_PARENT_PID", std::process::id().to_string())
            .env("TOPPILOT_RESOURCE_ROOT", resources.join("resources"))
            .env("TOPPILOT_DATA_DIR", &data)
            .env("IDESKTOP_V2_DATA_DIR", &data)
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
            project::project_pick_folder,
            project::project_open,
            project::project_list,
            project::project_read,
            project::project_save,
            project::project_create,
            project::project_rename,
            project::project_search,
            project::patch_preview,
            project::patch_apply,
            project::webview_create,
            project::webview_navigate,
            project::webview_close
        ])
        .run(tauri::generate_context!())
        .expect("error while running TopOptPilot desktop");
}
