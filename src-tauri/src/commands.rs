use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::io::{Write, BufRead, BufReader};
use tauri::Emitter;

fn find_python_engine() -> Result<(PathBuf, PathBuf), String> {
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    
    let candidates = vec![
        cwd.clone(),
        cwd.parent().unwrap_or(&cwd).to_path_buf(),
        cwd.parent().and_then(|p| p.parent()).unwrap_or(&cwd).to_path_buf(),
    ];

    for base in candidates {
        let engine_dir = base.join("python-engine");
        if engine_dir.exists() && engine_dir.is_dir() {
            let venv_exe = if cfg!(target_os = "windows") {
                engine_dir.join(".venv").join("Scripts").join("python.exe")
            } else {
                engine_dir.join(".venv").join("bin").join("python")
            };

            let python_exe = if venv_exe.exists() {
                venv_exe
            } else {
                PathBuf::from(if cfg!(target_os = "windows") { "python" } else { "python3" })
            };

            let main_script = engine_dir.join("main.py");
            return Ok((python_exe, main_script));
        }
    }

    Err("No se pudo localizar el directorio python-engine. Asegúrate de ejecutar la app desde el repositorio.".to_string())
}

#[tauri::command]
pub async fn run_python(
    app: tauri::AppHandle,
    command: String,
    args: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let (python_exe, script_path) = find_python_engine()?;

    let input_payload = serde_json::json!({
        "command": command,
        "args": args
    });
    
    let input_str = serde_json::to_string(&input_payload)
        .map_err(|e| format!("Error al serializar entrada: {}", e))?;

    let mut child = Command::new(python_exe)
        .arg(&script_path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Error al lanzar el motor de Python: {}. Asegúrate de que Python está instalado y que has ejecutado 'pip install -r requirements.txt' en python-engine.", e))?;

    if let Some(mut stdin) = child.stdin.take() {
        stdin.write_all(input_str.as_bytes())
            .map_err(|e| format!("Error al escribir en stdin de Python: {}", e))?;
    }

    let stdout = child.stdout.take().ok_or("No se pudo capturar stdout de Python")?;
    let stderr = child.stderr.take().ok_or("No se pudo capturar stderr de Python")?;

    let app_handle = app.clone();
    let stderr_thread = std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line_result in reader.lines() {
            if let Ok(line) = line_result {
                let _ = app_handle.emit("python-log", line);
            }
        }
    });

    let stdout_reader = BufReader::new(stdout);
    let mut stdout_content = String::new();
    for line in stdout_reader.lines() {
        if let Ok(l) = line {
            stdout_content.push_str(&l);
        }
    }

    let status = child.wait().map_err(|e| format!("Error esperando al proceso Python: {}", e))?;
    let _ = stderr_thread.join();

    if !status.success() {
        return Err(format!("El proceso Python falló con código de salida: {}", status));
    }

    let response: serde_json::Value = serde_json::from_str(&stdout_content)
        .map_err(|e| format!("Error al parsear JSON del motor de Python: {}. Salida cruda: {}", e, stdout_content))?;

    Ok(response)
}
