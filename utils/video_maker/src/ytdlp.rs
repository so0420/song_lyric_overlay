// yt-dlp 자식 프로세스를 감싼다: 유튜브 URL에서 음원(mp3)을, 옵션에 따라
// 썸네일(jpg)을 받아 임시 폴더에 내려받고 결과 경로를 돌려준다. 진행률은
// yt-dlp의 `[download] nn%` 줄을 파싱해 상태 메시지로 전달한다.

use crate::encoder::Progress;
use anyhow::{anyhow, Context, Result};
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::Sender;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const THUMB_EXTS: &[&str] = &["jpg", "jpeg", "png", "webp"];

pub struct DownloadResult {
    /// 추출된 음원 파일(mp3) 경로.
    pub audio: PathBuf,
    /// `want_thumbnail`이 켜져 있고 받기에 성공했을 때의 썸네일 이미지 경로.
    pub thumbnail: Option<PathBuf>,
    /// 영상 파일 이름에 쓸 영상 제목(음원 파일 stem).
    pub title: String,
}

/// 유튜브 `url`의 음원을 `dest_dir`(비어 있는 임시 폴더)에 mp3로 내려받는다.
pub fn download_audio(
    yt_dlp: &Path,
    ffmpeg: &Path,
    url: &str,
    dest_dir: &Path,
    want_thumbnail: bool,
    tx: &Sender<Progress>,
) -> Result<DownloadResult> {
    std::fs::create_dir_all(dest_dir)?;

    let _ = tx.send(Progress::Percent(0.0));
    let _ = tx.send(Progress::Status("유튜브 정보 가져오는 중…".into()));

    let mut cmd = Command::new(yt_dlp);
    // 내장 ffmpeg는 캐시에 `ffmpeg-<stamp>.exe`처럼 풀려 있어 표준 이름이 아니다.
    // 따라서 폴더가 아니라 ffmpeg 실행 파일 "경로"를 직접 넘겨야 yt-dlp가 찾는다.
    cmd.arg("--ffmpeg-location").arg(ffmpeg);
    cmd.args([
        "--no-mtime",
        "--newline",
        "--no-playlist",
        "--no-part",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
    ]);
    if want_thumbnail {
        cmd.args(["--write-thumbnail", "--convert-thumbnails", "jpg"]);
    }
    cmd.arg("-o");
    cmd.arg(dest_dir.join("%(title)s.%(ext)s"));
    cmd.arg(url);

    // 한국어(cp949) Windows에서 yt-dlp가 stdout에 유니코드(제목/이모지 등)를
    // 출력하다 `OSError: [Errno 22]`로 죽는 문제를 막기 위해 Python을 UTF-8
    // 모드로 강제한다.
    cmd.env("PYTHONUTF8", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");

    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    let mut child = cmd.spawn().context("yt-dlp 실행 실패")?;
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();

    let stderr_handle = std::thread::spawn(move || {
        let mut buf = String::new();
        let _ = BufReader::new(stderr).read_to_string(&mut buf);
        buf
    });

    // 콘솔이 없는 GUI 환경에서 yt-dlp는 stdout(파이프)에 cp949 등 로케일 인코딩으로
    // 출력할 수 있다. UTF-8이 아닌 줄에서 멈추면 파이프가 막혀 yt-dlp가 stdout 쓰기에서
    // [Errno 22]로 죽으므로, 바이트 단위로 끝까지 읽고 lossy 디코딩한다.
    let mut reader = BufReader::new(stdout);
    let mut bytes = Vec::new();
    loop {
        bytes.clear();
        match reader.read_until(b'\n', &mut bytes) {
            Ok(0) | Err(_) => break,
            Ok(_) => {}
        }
        let line = String::from_utf8_lossy(&bytes);
        let line = line.trim_end();
        if let Some(pct) = parse_progress(line) {
            let _ = tx.send(Progress::Status(format!("유튜브 음원 다운로드 {:.0}%", pct * 100.0)));
        } else if line.contains("[ExtractAudio]") {
            let _ = tx.send(Progress::Status("음원 추출 중…".into()));
        }
    }

    let status = child.wait()?;
    let stderr_text = stderr_handle.join().unwrap_or_default();

    if !status.success() {
        return Err(anyhow!(
            "yt-dlp 종료 코드 {:?}: {}",
            status.code(),
            stderr_text
                .lines()
                .rev()
                .take(5)
                .collect::<Vec<_>>()
                .join(" | ")
        ));
    }

    let audio = find_file_with_ext(dest_dir, &["mp3"])?
        .ok_or_else(|| anyhow!("다운로드된 mp3 파일을 찾을 수 없음"))?;
    let title = audio
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "youtube".to_string());
    let thumbnail = if want_thumbnail {
        find_file_with_ext(dest_dir, THUMB_EXTS)?
    } else {
        None
    };

    Ok(DownloadResult {
        audio,
        thumbnail,
        title,
    })
}

/// `dir` 안에서 주어진 확장자 중 하나를 가진 첫 파일을 찾는다.
fn find_file_with_ext(dir: &Path, exts: &[&str]) -> Result<Option<PathBuf>> {
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        let ext = path
            .extension()
            .and_then(|s| s.to_str())
            .map(|s| s.to_ascii_lowercase())
            .unwrap_or_default();
        if exts.contains(&ext.as_str()) {
            return Ok(Some(path));
        }
    }
    Ok(None)
}

fn parse_progress(line: &str) -> Option<f32> {
    // 예: "[download]  45.3% of 12.34MiB at 1.23MiB/s ETA 00:05"
    let rest = line.trim_start().strip_prefix("[download]")?.trim_start();
    let token = rest.split_whitespace().next()?;
    let pct = token.strip_suffix('%')?;
    pct.parse::<f32>().ok().map(|p| (p / 100.0).clamp(0.0, 1.0))
}
