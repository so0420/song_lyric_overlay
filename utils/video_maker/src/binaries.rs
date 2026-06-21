use anyhow::{anyhow, Result};
use std::fs;
use std::io::Cursor;
use std::path::PathBuf;

const FFMPEG_ZST: &[u8] = include_bytes!("../resources/ffmpeg.exe.zst");
const YTDLP_ZST: &[u8] = include_bytes!("../resources/yt-dlp.exe.zst");

pub struct Binaries {
    pub ffmpeg: PathBuf,
    pub yt_dlp: PathBuf,
}

/// 앱 전용 캐시 디렉터리(`%LOCALAPPDATA%\..\VideoMaker`)를 만들고 경로를 돌려준다.
pub fn cache_dir() -> Result<PathBuf> {
    let dir = dirs::cache_dir()
        .ok_or_else(|| anyhow!("cache 디렉터리를 찾을 수 없음"))?
        .join("VideoMaker");
    fs::create_dir_all(&dir)?;
    Ok(dir)
}

/// 내장된 ffmpeg / yt-dlp를 캐시에 풀어 실행 가능한 경로를 돌려준다.
pub fn extract() -> Result<Binaries> {
    let dir = cache_dir()?;
    let ffmpeg = extract_one(&dir, "ffmpeg", FFMPEG_ZST)?;
    let yt_dlp = extract_one(&dir, "yt-dlp", YTDLP_ZST)?;
    Ok(Binaries { ffmpeg, yt_dlp })
}

fn extract_one(dir: &std::path::Path, name: &str, data: &[u8]) -> Result<PathBuf> {
    let stamp = format!("{:016x}", fingerprint(data));
    let path = dir.join(format!("{name}-{stamp}.exe"));

    if !path.exists() {
        let decompressed = zstd::decode_all(Cursor::new(data))?;
        let tmp = path.with_extension("exe.tmp");
        fs::write(&tmp, &decompressed)?;
        fs::rename(&tmp, &path)?;
    }

    Ok(path)
}

fn fingerprint(data: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    let sample = &data[..data.len().min(8192)];
    for &b in sample {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h ^= data.len() as u64;
    h
}
