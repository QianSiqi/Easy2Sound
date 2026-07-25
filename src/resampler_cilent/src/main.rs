use std::env;
use std::process;
use reqwest::header::{CONTENT_LENGTH, USER_AGENT, CONTENT_TYPE};
use reqwest::Client;
use std::time::Duration;

// 服务端配置
const SERVER_URL: &str = "http://127.0.0.1:8572";
const PORT_CHECK_TIMEOUT_MS: u64 = 25;

/// 检查端口是否被占用（模拟C#的IsPortInUse逻辑）
fn is_port_in_use(port: u16) -> bool {
    match std::net::TcpStream::connect_timeout(
        &(std::net::SocketAddr::from(([127, 0, 0, 1], port))),
        Duration::from_millis(PORT_CHECK_TIMEOUT_MS)
    ) {
        Ok(_) => true,
        Err(_) => false,
    }
}

/// 显示使用帮助
fn print_usage() {
    println!("usage: resampler in_file out_file pitch velocity [flags] [offset] [length] [consonant] [cutoff] [volume] [modulation] [tempo] [pitch_string]");
    println!("\nResamples using the PC-NSF-HIFIGAN Vocoder.\n");
    println!("arguments:");
    println!("\tin_file\t\tPath to input file.");
    println!("\tout_file\tPath to output file.");
    println!("\tpitch\t\tThe pitch to render on.");
    println!("\tvelocity\tThe consonant velocity of the render.\n");
    println!("optional arguments:");
    println!("\tflags\t\tThe flags of the render. But now, it's not implemented yet.");
    println!("\toffset\t\tThe offset from the start of the render area of the sample. (default: 0)");
    println!("\tlength\t\tThe length of the stretched area in milliseconds. (default: 1000)");
    println!("\tconsonant\tThe unstretched area of the render in milliseconds. (default: 0)");
    println!("\tcutoff\t\tThe cutoff from the end or from the offset for the render area of the sample. (default: 0)");
    println!("\tvolume\t\tThe volume of the render in percentage. (default: 100)");
    println!("\tmodulation\tThe pitch modulation of the render in percentage. (default: 0)");
    println!("\ttempo\t\tThe tempo of the render. Needs to have a ! at the start. (default: !100)");
    println!("\tpitch_string\tThe UTAU pitchbend parameter written in Base64 with RLE encoding. (default: AA)");
}

/// 发送POST请求到服务端（精确复刻C#的HTTP请求）
async fn send_post_request(args: &[String]) -> Result<(), String> {
    // 构建请求体：和C#完全一致的空格分隔字符串
    let post_fields = args.join(" ");
    println!("[DEBUG] 发送的请求体: {}", post_fields);

    // 构建和C# HttpClient完全一致的请求头
    let client = Client::builder()
        .user_agent("rust-http-client/1.0") // 模拟C#的默认User-Agent
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| format!("创建HTTP客户端失败: {}", e))?;

    // 计算内容长度（C#会自动设置）
    let content_length = post_fields.as_bytes().len() as u64;

    // 构建请求：精确匹配C#的StringContent行为
    let response = client
        .post(SERVER_URL)
        .header(CONTENT_TYPE, "application/x-www-form-urlencoded; charset=utf-8")
        .header(CONTENT_LENGTH, content_length)
        .header(USER_AGENT, "rust-http-client/1.0")
        .body(post_fields)
        .send()
        .await
        .map_err(|e| {
            let err_msg = format!("发送请求失败: {}", e);
            // 更详细的错误诊断
            if err_msg.contains("connection closed") {
                format!("{}\n提示：服务端关闭了连接，可能是请求格式/头信息不匹配", err_msg)
            } else {
                err_msg
            }
        })?;

    // 处理响应（完全匹配C#的错误码逻辑）
    match response.status() {
        reqwest::StatusCode::OK => {
            println!("Success:  Resampled Sucessfully");
        }
        reqwest::StatusCode::BAD_REQUEST => {
            eprintln!("Error: got an incorrect amount of arguments or the arguments were out of order. Please check the input data before continuing.");
            return Err("参数错误".to_string());
        }
        reqwest::StatusCode::INTERNAL_SERVER_ERROR => {
            let error_details = response.text().await.unwrap_or_else(|_| "无详细信息".to_string());
            eprintln!("Error: An Internal Error occured in erver. Check your voicebank wav files to ensure they are the correct format. More details:\n{}", error_details);
            return Err("服务端内部错误".to_string());
        }
        other => {
            eprintln!("Error: returned {}", other);
            return Err(format!("服务端返回错误码: {}", other));
        }
    }

    Ok(())
}

#[tokio::main]
async fn main() {
    // 获取命令行参数（跳过程序名）
    let args: Vec<String> = env::args().skip(1).collect();

    // 检查参数是否为空
    if args.is_empty() {
        eprintln!("[Main] No arguments provided.");
        print_usage();
        process::exit(1);
    }

    // 检查服务端端口是否可用
    println!("[Main] Checking if port {} is in use...", 8572);
    if !is_port_in_use(8572) {
        eprintln!("[Main] Error: 服务端未运行（端口8572未被占用），请先启动Server！");
        process::exit(1);
    }

    // 发送请求
    match send_post_request(&args).await {
        Ok(_) => process::exit(0),
        Err(e) => {
            eprintln!("[Main] 请求失败: {}", e);
            process::exit(1);
        }
    }
}