// server_onnx_rs — Rust 版 HifiSampler 服务器（onnxruntime 推理）
// 用法：
//   server_onnx_rs.exe            → HTTP 服务器（8572 端口，兼容 UTAU resampler 协议）
//   server_onnx_rs.exe "<args>"   → 命令行直接渲染（参数格式与 HTTP POST 相同）
mod config;
mod hnsep;
mod log;
mod mel;
mod pitch;
mod resampler;
mod wav;

use std::io::Read;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use config::Config;
use hnsep::HnsepModel;
use mel::MelAnalysis;
use ort::session::Session;
use resampler::{save_wav, RenderArgs, Resampler};

fn default_dll_path() -> String {
    if let Ok(p) = std::env::var("ORT_DYLIB_PATH") {
        if !p.is_empty() { return p; }
    }
    let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf()));
    let mut candidates: Vec<std::path::PathBuf> = Vec::new();
    if let Some(d) = &exe_dir {
        // 部署布局：exe 同目录放 onnxruntime.dll + DirectML.dll
        candidates.push(d.join("onnxruntime.dll"));
        // 开发布局：exe 在 server_onnx_rs/target/release，DLL 在 server_onnx_rs/
        candidates.push(d.join(r"..\onnxruntime.dll"));
        candidates.push(d.join(r"..\..\onnxruntime.dll"));
    }
    // CWD 下的 onnxruntime.dll
    candidates.push(std::path::PathBuf::from("onnxruntime.dll"));
    for c in candidates {
        if c.exists() { return c.to_string_lossy().into_owned(); }
    }
    "onnxruntime.dll".to_string()
}

/// 查找模型/配置文件：依次尝试 CWD、exe 同目录、exe 上两级（开发布局）
fn find_file(rel: &str) -> std::path::PathBuf {
    let mut bases: Vec<std::path::PathBuf> = vec![std::path::PathBuf::from(".")];
    if let Some(d) = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())) {
        bases.push(d.clone());
        bases.push(d.join(".."));
        bases.push(d.join("..").join(".."));
    }
    for base in &bases {
        let p = base.join(rel);
        if p.exists() { return p; }
    }
    std::path::PathBuf::from(rel)
}

fn main() {
    log::info("server_onnx_rs starting");

    // config.yaml 优先从 exe 目录加载（部署时 CWD 可能不是 exe 目录）
    let cfg_dir = {
        let d = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf()));
        let mut dirs: Vec<std::path::PathBuf> = vec![std::path::PathBuf::from(".")];
        if let Some(d) = &d {
            dirs.push(d.clone());
            dirs.push(d.join(".."));
        }
        dirs.into_iter().find(|p| p.join("config.yaml").exists()).unwrap_or_else(|| std::path::PathBuf::from("."))
    };
    let cfg = Config::load(&cfg_dir);

    // 加载 onnxruntime DLL
    let dll = default_dll_path();
    unsafe { std::env::set_var("ORT_DYLIB_PATH", &dll); }
    log::info(&format!("onnxruntime DLL: {dll}"));

    // 加载 vocoder（CWD → exe 目录 → exe 上两级逐级查找）
    let default_rel = r"pc_nsf_hifigan_44.1k_hop512_128bin_2025.02\model.onnx";
    let vocoder_path = find_file(&cfg.vocoder_path);
    let vocoder_path = if vocoder_path.exists() {
        vocoder_path
    } else {
        let fallback = find_file(default_rel);
        if fallback.exists() {
            fallback
        } else {
            log::error(&format!("vocoder model not found: {}", cfg.vocoder_path));
            std::process::exit(1);
        }
    };
    log::info(&format!("loading vocoder: {}", vocoder_path.display()));
    let mut builder = match Session::builder() {
        Ok(b) => b,
        Err(e) => {
            log::error(&format!("failed to build session: {e}"));
            std::process::exit(1);
        }
    };
    let session = match builder.commit_from_file(&vocoder_path) {
        Ok(s) => s,
        Err(e) => {
            log::error(&format!("failed to load vocoder: {e}"));
            std::process::exit(1);
        }
    };
    let session = Arc::new(Mutex::new(session));
    log::info("vocoder loaded");

    // 加载 HN-SEP（可选：失败不影响主流程，Hb/Hv/Ht 时会报错）
    let hnsep_path = find_file(&cfg.hnsep_model_path);
    let hnsep_arc: Option<Arc<Mutex<Session>>> = if hnsep_path.exists() {
        log::info(&format!("loading HN-SEP: {}", hnsep_path.display()));
        match Session::builder().and_then(|mut b| b.commit_from_file(&hnsep_path)) {
            Ok(s) => Some(Arc::new(Mutex::new(s))),
            Err(e) => {
                log::warn(&format!("failed to load HN-SEP, Hb/Hv/Ht flags unavailable: {e}"));
                None
            }
        }
    } else {
        log::warn(&format!("HN-SEP model not found: {}, Hb/Hv/Ht flags unavailable", cfg.hnsep_model_path));
        None
    };
    let hnsep_model: Option<HnsepModel> = hnsep_arc.as_ref().map(|s| {
        // hnsep 的 config.yaml 提供 n_fft/hop_length/sr
        let (n_fft, hop, sr) = load_hnsep_params(&hnsep_path);
        log::info(&format!("HN-SEP params: n_fft={n_fft} hop={hop} sr={sr}"));
        HnsepModel::new(s, n_fft, hop, sr)
    });
    if hnsep_model.is_some() {
        log::info("HN-SEP loaded");
    }

    let mel_analysis = MelAnalysis::new(
        cfg.sample_rate, cfg.n_fft, cfg.win_size, cfg.origin_hop_size,
        cfg.mel_fmin, cfg.mel_fmax, cfg.n_mels,
    );

    // 命令行直跑模式
    let args: Vec<String> = std::env::args().skip(1).collect();
    if !args.is_empty() {
        let input = args.join(" ");
        match handle_render(&input, &cfg, &mel_analysis, &session, hnsep_model.as_ref()) {
            Ok(msg) => log::info(&format!("Success: {msg}")),
            Err(e) => { log::error(&format!("render failed: {e}")); std::process::exit(1); }
        }
        return;
    }

    // HTTP 服务器（8572 端口，与 python 版一致）
    let server = tiny_http::Server::http("0.0.0.0:8572").expect("failed to bind :8572");
    log::info("Listening on port 8572");
    for request in server.incoming_requests() {
        let result = match request.method() {
            &tiny_http::Method::Get => {
                request.respond(tiny_http::Response::from_string("Server Ready")
                    .with_status_code(200))
            }
            &tiny_http::Method::Post => {
                let mut content = String::new();
                let mut request = request;
                let read_ok = request.as_reader().read_to_string(&mut content).is_ok();
                if !read_ok {
                    log::warn("failed to read request body");
                    request.respond(tiny_http::Response::from_string("Failed to read body")
                        .with_status_code(400))
                } else {
                    log::info(&format!("received: {content}"));
                    let t0 = Instant::now();
                    // catch_unwind：任何 panic 都返回 500，不能杀死服务器进程
                    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        handle_render(&content, &cfg, &mel_analysis, &session, hnsep_model.as_ref())
                    }));
                    let response = match result {
                        Ok(Ok(msg)) => {
                            log::info(&format!("render OK in {:.1}s: {msg}", t0.elapsed().as_secs_f32()));
                            tiny_http::Response::from_string(format!("Success: {msg}"))
                                .with_status_code(200)
                        }
                        Ok(Err(e)) => {
                            log::error(&format!("render failed in {:.1}s: {e}", t0.elapsed().as_secs_f32()));
                            tiny_http::Response::from_string(format!("Error: {e}"))
                                .with_status_code(500)
                        }
                        Err(_) => {
                            log::error(&format!("render panicked in {:.1}s (internal bug)", t0.elapsed().as_secs_f32()));
                            tiny_http::Response::from_string("Error: internal panic")
                                .with_status_code(500)
                        }
                    };
                    request.respond(response)
                }
            }
            _ => request.respond(tiny_http::Response::from_string("Method not allowed")
                .with_status_code(405)),
        };
        if let Err(e) = result {
            log::error(&format!("respond failed: {e}"));
        }
    }
}

/// 读取 hnsep/vr/config.yaml 的 n_fft / hop_length / sr
fn load_hnsep_params(model_path: &std::path::Path) -> (usize, usize, usize) {
    let mut n_fft = 2048usize;
    let mut hop = 512usize;
    let mut sr = 44100usize;
    if let Some(dir) = model_path.parent() {
        let cfg_path = dir.join("config.yaml");
        if let Ok(text) = std::fs::read_to_string(&cfg_path) {
            if let Ok(docs) = yaml_rust2::YamlLoader::load_from_str(&text) {
                if let Some(root) = docs.first().and_then(|d| d.as_hash()) {
                    let get = |k: &str| root.get(&yaml_rust2::Yaml::String(k.into())).and_then(|v| v.as_i64());
                    if let Some(v) = get("n_fft") { n_fft = v as usize; }
                    if let Some(v) = get("hop_length") { hop = v as usize; }
                    if let Some(v) = get("sr") { sr = v as usize; }
                }
            }
        }
    }
    (n_fft, hop, sr)
}

/// 渲染一个请求，返回成功消息
fn handle_render(input: &str, cfg: &Config, mel_analysis: &MelAnalysis, session: &Arc<Mutex<Session>>,
                 hnsep: Option<&HnsepModel>) -> Result<String, String> {
    let args = RenderArgs::from_str(input)?;
    let out_name = args.out_file.clone();
    log::info(&format!(
        "render start: {} -> {} pitch={} velocity={} flags={} length={}ms",
        args.in_file.display(), args.out_file.display(), args.pitch, args.velocity, args.flags, args.length
    ));
    let resampler = Resampler::new(cfg, mel_analysis, session, hnsep);
    let render = resampler.render(&args)?;
    save_wav(&args.out_file, &render, cfg.sample_rate)?;
    Ok(format!("'{}' -> '{}'", args.in_file.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default(),
               out_name.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()))
}
