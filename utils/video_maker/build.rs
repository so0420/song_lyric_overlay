use std::fs;
use std::io::{self, Cursor, Read};
use std::path::{Path, PathBuf};
use std::time::Duration;

const FFMPEG_URL: &str =
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip";
const YTDLP_URL: &str = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe";

fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    let resources = PathBuf::from("resources");
    fs::create_dir_all(&resources).expect("failed to create resources/");

    let default_image = resources.join("default_image.jpg");
    if !default_image.exists() {
        panic!(
            "resources/default_image.jpg가 없습니다. 잼쿠프로필.jpg를 해당 경로에 복사해 주세요."
        );
    }

    prepare_ffmpeg(&resources);
    prepare_ytdlp(&resources);
}

/// ffmpeg.exe를 받아 zip에서 추출 후 zstd로 압축해 resources/ffmpeg.exe.zst 생성.
fn prepare_ffmpeg(resources: &Path) {
    let compressed_path = resources.join("ffmpeg.exe.zst");
    if compressed_path.exists() {
        return;
    }

    eprintln!("[video_maker build] Downloading ffmpeg (~100MB, once)...");
    let zip_bytes = download(FFMPEG_URL).expect("ffmpeg 다운로드 실패");

    eprintln!("[video_maker build] Extracting ffmpeg.exe from zip...");
    let exe_bytes = extract_ffmpeg_from_zip(&zip_bytes).expect("zip에서 ffmpeg.exe 추출 실패");

    eprintln!(
        "[video_maker build] Compressing ffmpeg {}MB with zstd level 22 (slow, once)...",
        exe_bytes.len() / 1_000_000
    );
    let compressed = zstd::encode_all(Cursor::new(&exe_bytes), 22).expect("ffmpeg zstd 압축 실패");

    fs::write(&compressed_path, &compressed).expect("ffmpeg compressed 파일 쓰기 실패");
    eprintln!(
        "[video_maker build] Done. ffmpeg.exe: {}MB -> {}MB",
        exe_bytes.len() / 1_000_000,
        compressed.len() / 1_000_000
    );
}

/// yt-dlp.exe를 (resources/yt-dlp.exe가 있으면 그걸, 없으면 다운로드해서) zstd로
/// 압축해 resources/yt-dlp.exe.zst 생성.
fn prepare_ytdlp(resources: &Path) {
    let compressed_path = resources.join("yt-dlp.exe.zst");
    if compressed_path.exists() {
        return;
    }

    let raw_path = resources.join("yt-dlp.exe");
    let exe_bytes = if raw_path.exists() {
        eprintln!("[video_maker build] Using bundled resources/yt-dlp.exe...");
        fs::read(&raw_path).expect("yt-dlp.exe 읽기 실패")
    } else {
        eprintln!("[video_maker build] Downloading yt-dlp.exe (~18MB, once)...");
        download(YTDLP_URL).expect("yt-dlp 다운로드 실패")
    };

    // yt-dlp.exe는 이미 PyInstaller로 압축된 실행 파일이라 추가 압축률은 낮다.
    // 빌드 속도를 위해 level 19를 쓴다.
    eprintln!(
        "[video_maker build] Compressing yt-dlp {}MB with zstd level 19 (once)...",
        exe_bytes.len() / 1_000_000
    );
    let compressed = zstd::encode_all(Cursor::new(&exe_bytes), 19).expect("yt-dlp zstd 압축 실패");

    fs::write(&compressed_path, &compressed).expect("yt-dlp compressed 파일 쓰기 실패");
    eprintln!(
        "[video_maker build] Done. yt-dlp.exe: {}MB -> {}MB",
        exe_bytes.len() / 1_000_000,
        compressed.len() / 1_000_000
    );
}

fn download(url: &str) -> io::Result<Vec<u8>> {
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(30))
        .timeout_read(Duration::from_secs(600))
        .build();
    let resp = agent
        .get(url)
        .call()
        .map_err(|e| io::Error::new(io::ErrorKind::Other, e.to_string()))?;
    let mut buf = Vec::with_capacity(120 * 1024 * 1024);
    resp.into_reader().read_to_end(&mut buf)?;
    Ok(buf)
}

fn extract_ffmpeg_from_zip(zip_bytes: &[u8]) -> io::Result<Vec<u8>> {
    let reader = Cursor::new(zip_bytes);
    let mut archive = zip::ZipArchive::new(reader)
        .map_err(|e| io::Error::new(io::ErrorKind::Other, e.to_string()))?;

    for i in 0..archive.len() {
        let mut file = archive
            .by_index(i)
            .map_err(|e| io::Error::new(io::ErrorKind::Other, e.to_string()))?;
        let name = file.name().replace('\\', "/");
        if name.ends_with("/bin/ffmpeg.exe") {
            let mut buf = Vec::with_capacity(file.size() as usize);
            file.read_to_end(&mut buf)?;
            return Ok(buf);
        }
    }
    Err(io::Error::new(
        io::ErrorKind::NotFound,
        "ffmpeg.exe not found in zip",
    ))
}
