use crate::encoder::{run_job, EncodeJob, Progress};
use crate::ytdlp;
use eframe::egui;
use std::io::Read;
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::thread;
use std::time::Duration;

const DEFAULT_IMAGE_BYTES: &[u8] = include_bytes!("../resources/default_image.jpg");

const AUDIO_EXTS: &[&str] = &["mp3", "wav", "flac", "m4a", "ogg", "aac", "opus", "wma"];
const IMAGE_EXTS: &[&str] = &["jpg", "jpeg", "png", "webp", "bmp"];

#[derive(Clone, Debug)]
enum ImageSource {
    Default,
    LocalFile(PathBuf),
    Url(String),
}

/// 변환 대상 한 건. 로컬 오디오 파일이거나 유튜브 링크.
#[derive(Clone, Debug)]
enum JobSource {
    Local(PathBuf),
    YouTube(String),
}

#[derive(Debug)]
enum JobState {
    Idle,
    Running,
    Finished,
}

pub struct App {
    ffmpeg_path: PathBuf,
    yt_dlp_path: PathBuf,

    image_source: ImageSource,
    url_input: String,

    audio_files: Vec<PathBuf>,
    yt_input: String,
    use_yt_thumbnail: bool,
    output_dir: Option<PathBuf>,

    state: JobState,
    rx: Option<Receiver<Progress>>,
    current_percent: f32,
    current_status: String,
    total_jobs: usize,
    attempted_jobs: usize,
    success_jobs: usize,
    log: Vec<String>,
}

impl App {
    pub fn new(ffmpeg_path: PathBuf, yt_dlp_path: PathBuf) -> Self {
        Self {
            ffmpeg_path,
            yt_dlp_path,
            image_source: ImageSource::Default,
            url_input: String::new(),
            audio_files: Vec::new(),
            yt_input: String::new(),
            use_yt_thumbnail: false,
            output_dir: None,
            state: JobState::Idle,
            rx: None,
            current_percent: 0.0,
            current_status: String::new(),
            total_jobs: 0,
            attempted_jobs: 0,
            success_jobs: 0,
            log: Vec::new(),
        }
    }

    fn image_source_label(&self) -> String {
        match &self.image_source {
            ImageSource::Default => "기본 이미지 (잼쿠프로필.jpg)".into(),
            ImageSource::LocalFile(p) => format!("파일: {}", p.display()),
            ImageSource::Url(u) => format!("URL: {u}"),
        }
    }

    /// 입력란의 유튜브 링크들을 한 줄에 하나씩 파싱한다.
    fn youtube_urls(&self) -> Vec<String> {
        self.yt_input
            .lines()
            .map(|l| l.trim())
            .filter(|l| !l.is_empty())
            .map(|l| l.to_string())
            .collect()
    }

    fn start_encoding(&mut self) {
        let yt_urls = self.youtube_urls();

        let mut sources: Vec<JobSource> = self
            .audio_files
            .iter()
            .cloned()
            .map(JobSource::Local)
            .collect();
        sources.extend(yt_urls.into_iter().map(JobSource::YouTube));

        if sources.is_empty() {
            self.log
                .push("오디오 파일을 추가하거나 유튜브 링크를 입력해 주세요.".into());
            return;
        }

        let (tx, rx) = channel();
        let ffmpeg_path = self.ffmpeg_path.clone();
        let yt_dlp_path = self.yt_dlp_path.clone();
        let image_source = self.image_source.clone();
        let output_dir = self.output_dir.clone();
        let use_yt_thumbnail = self.use_yt_thumbnail;

        self.total_jobs = sources.len();
        self.attempted_jobs = 0;
        self.success_jobs = 0;
        self.current_percent = 0.0;
        self.current_status = "준비 중…".into();
        self.state = JobState::Running;
        self.rx = Some(rx);
        self.log.clear();

        thread::spawn(move || {
            // 전역 이미지는 실제로 필요할 때(로컬 파일 또는 썸네일 미사용 유튜브)만 준비한다.
            let needs_global = sources.iter().any(|s| match s {
                JobSource::Local(_) => true,
                JobSource::YouTube(_) => !use_yt_thumbnail,
            });
            let global_image = if needs_global {
                match resolve_image(&image_source, &tx) {
                    Ok(p) => Some(p),
                    Err(e) => {
                        let _ = tx.send(Progress::Status(format!("이미지 준비 실패: {e}")));
                        for s in &sources {
                            let _ = tx.send(Progress::JobFailed {
                                label: source_label(s),
                                message: format!("이미지 준비 실패: {e}"),
                            });
                        }
                        let _ = tx.send(Progress::AllDone);
                        return;
                    }
                }
            } else {
                None
            };

            for (i, source) in sources.iter().enumerate() {
                let _ = tx.send(Progress::Percent(0.0));
                let _ = tx.send(Progress::Status(format!(
                    "[{}/{}] {} 처리 중…",
                    i + 1,
                    sources.len(),
                    source_label(source)
                )));

                let prepared = match source {
                    JobSource::Local(audio) => {
                        let image = global_image.clone().expect("로컬 작업엔 전역 이미지 필요");
                        let output = output_path_for(&output_dir, audio);
                        Some((audio.clone(), image, output, None))
                    }
                    JobSource::YouTube(url) => {
                        let tmp_dir = match crate::binaries::cache_dir() {
                            Ok(d) => d.join("yt_dl").join(format!("job{i}")),
                            Err(e) => {
                                let _ = tx.send(Progress::JobFailed {
                                    label: source_label(source),
                                    message: format!("임시 폴더 준비 실패: {e}"),
                                });
                                continue;
                            }
                        };
                        let _ = std::fs::remove_dir_all(&tmp_dir);

                        match ytdlp::download_audio(
                            &yt_dlp_path,
                            &ffmpeg_path,
                            url,
                            &tmp_dir,
                            use_yt_thumbnail,
                            &tx,
                        ) {
                            Ok(res) => {
                                let image = match (use_yt_thumbnail, res.thumbnail.clone()) {
                                    (true, Some(t)) => t,
                                    _ => global_image.clone().unwrap_or_else(|| {
                                        // 썸네일 모드인데 썸네일을 못 받은 경우 기본 이미지로 대체.
                                        resolve_image(&ImageSource::Default, &tx)
                                            .unwrap_or_else(|_| PathBuf::from("default_image.jpg"))
                                    }),
                                };
                                let dir = youtube_output_dir(&output_dir);
                                let output = dir.join(format!("{}.mp4", sanitize(&res.title)));
                                Some((res.audio, image, output, Some(tmp_dir)))
                            }
                            Err(e) => {
                                let _ = tx.send(Progress::JobFailed {
                                    label: source_label(source),
                                    message: e.to_string(),
                                });
                                let _ = std::fs::remove_dir_all(&tmp_dir);
                                continue;
                            }
                        }
                    }
                };

                let Some((audio_path, image_path, output, tmp_dir)) = prepared else {
                    continue;
                };

                let _ = tx.send(Progress::Percent(0.0));
                let _ = tx.send(Progress::Status(format!(
                    "[{}/{}] {} 영상 변환 중…",
                    i + 1,
                    sources.len(),
                    output
                        .file_name()
                        .map(|s| s.to_string_lossy().into_owned())
                        .unwrap_or_default()
                )));

                let job = EncodeJob {
                    ffmpeg_path: ffmpeg_path.clone(),
                    image_path,
                    audio_path,
                    output_path: output.clone(),
                };

                match run_job(&job, &tx) {
                    Ok(()) => {
                        let _ = tx.send(Progress::JobSucceeded(output));
                    }
                    Err(e) => {
                        let _ = tx.send(Progress::JobFailed {
                            label: source_label(source),
                            message: e.to_string(),
                        });
                    }
                }

                // 유튜브 임시 다운로드 폴더 정리.
                if let Some(dir) = tmp_dir {
                    let _ = std::fs::remove_dir_all(&dir);
                }
            }

            let _ = tx.send(Progress::AllDone);
        });
    }

    fn pump_progress(&mut self) {
        let Some(rx) = &self.rx else { return };
        loop {
            match rx.try_recv() {
                Ok(Progress::Status(s)) => self.current_status = s,
                Ok(Progress::Percent(p)) => self.current_percent = p,
                Ok(Progress::JobSucceeded(path)) => {
                    self.attempted_jobs += 1;
                    self.success_jobs += 1;
                    self.log.push(format!("✓ {}", path.display()));
                }
                Ok(Progress::JobFailed { label, message }) => {
                    self.attempted_jobs += 1;
                    self.log.push(format!("✗ {label}: {message}"));
                }
                Ok(Progress::AllDone) => {
                    self.state = JobState::Finished;
                    self.current_status = format!(
                        "완료. 성공 {}개 / 실패 {}개",
                        self.success_jobs,
                        self.attempted_jobs - self.success_jobs
                    );
                    self.rx = None;
                    break;
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    self.rx = None;
                    break;
                }
            }
        }
    }

    fn handle_dropped(&mut self, ctx: &egui::Context) {
        let dropped: Vec<_> = ctx.input(|i| i.raw.dropped_files.clone());
        for f in dropped {
            let Some(path) = f.path else { continue };
            let ext = path
                .extension()
                .and_then(|s| s.to_str())
                .map(|s| s.to_ascii_lowercase())
                .unwrap_or_default();
            if AUDIO_EXTS.contains(&ext.as_str()) {
                self.audio_files.push(path);
            } else if IMAGE_EXTS.contains(&ext.as_str()) {
                self.image_source = ImageSource::LocalFile(path);
            }
        }
    }
}

impl eframe::App for App {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.pump_progress();
        self.handle_dropped(ctx);

        if matches!(self.state, JobState::Running) {
            ctx.request_repaint_after(Duration::from_millis(100));
        }

        egui::CentralPanel::default().show(ctx, |ui| {
            egui::ScrollArea::vertical().show(ui, |ui| {
            ui.heading("앨범 커버 영상 생성기");
            ui.small(
                "이미지 + 오디오(또는 유튜브 링크)로 유튜브 업로드용 mp4를 만듭니다. 파일을 창에 드래그해도 됩니다.",
            );
            ui.add_space(6.0);

            ui.group(|ui| {
                ui.label(egui::RichText::new("이미지").strong());
                ui.label(self.image_source_label());
                ui.horizontal(|ui| {
                    if ui.button("기본 이미지 사용").clicked() {
                        self.image_source = ImageSource::Default;
                    }
                    if ui.button("파일 선택…").clicked() {
                        if let Some(p) = rfd::FileDialog::new()
                            .add_filter("Image", IMAGE_EXTS)
                            .pick_file()
                        {
                            self.image_source = ImageSource::LocalFile(p);
                        }
                    }
                });
                ui.horizontal(|ui| {
                    ui.label("URL:");
                    let r = ui.add(
                        egui::TextEdit::singleline(&mut self.url_input)
                            .hint_text("https://…")
                            .desired_width(f32::INFINITY),
                    );
                    if r.lost_focus() && !self.url_input.trim().is_empty() {
                        self.image_source = ImageSource::Url(self.url_input.trim().to_string());
                    }
                });
            });

            ui.add_space(4.0);

            ui.group(|ui| {
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("YouTube 링크 (음원)").strong());
                    let n = self.youtube_urls().len();
                    if n > 0 {
                        ui.label(format!("({n}개)"));
                    }
                });
                ui.small("한 줄에 하나씩 붙여넣으세요. 유튜브에서 음원을 받아 영상으로 만듭니다.");
                ui.add(
                    egui::TextEdit::multiline(&mut self.yt_input)
                        .hint_text("https://www.youtube.com/watch?v=...\nhttps://youtu.be/...")
                        .desired_rows(3)
                        .desired_width(f32::INFINITY),
                );
                ui.checkbox(
                    &mut self.use_yt_thumbnail,
                    "유튜브 썸네일을 이미지로 사용 (위 이미지 대신)",
                );
            });

            ui.add_space(4.0);

            ui.group(|ui| {
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("오디오 파일").strong());
                    ui.label(format!("({}개)", self.audio_files.len()));
                });
                ui.horizontal(|ui| {
                    if ui.button("파일 추가…").clicked() {
                        if let Some(files) = rfd::FileDialog::new()
                            .add_filter("Audio", AUDIO_EXTS)
                            .pick_files()
                        {
                            self.audio_files.extend(files);
                        }
                    }
                    if ui.button("비우기").clicked() {
                        self.audio_files.clear();
                    }
                });

                egui::ScrollArea::vertical()
                    .max_height(120.0)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        let mut remove = None;
                        for (i, f) in self.audio_files.iter().enumerate() {
                            ui.horizontal(|ui| {
                                if ui.small_button("✗").clicked() {
                                    remove = Some(i);
                                }
                                ui.label(
                                    f.file_name()
                                        .map(|s| s.to_string_lossy().into_owned())
                                        .unwrap_or_default(),
                                );
                            });
                        }
                        if let Some(i) = remove {
                            self.audio_files.remove(i);
                        }
                    });
            });

            ui.add_space(4.0);

            ui.group(|ui| {
                ui.label(egui::RichText::new("출력 폴더").strong());
                ui.label(match &self.output_dir {
                    Some(p) => format!("{}", p.display()),
                    None => "(지정 안 함 — 프로그램(exe)과 같은 폴더에 저장)".to_string(),
                });
                ui.horizontal(|ui| {
                    if ui.button("폴더 선택…").clicked() {
                        if let Some(p) = rfd::FileDialog::new().pick_folder() {
                            self.output_dir = Some(p);
                        }
                    }
                    if ui.button("기본값으로").clicked() {
                        self.output_dir = None;
                    }
                });
            });

            ui.add_space(6.0);

            let is_running = matches!(self.state, JobState::Running);
            ui.add_enabled_ui(!is_running, |ui| {
                let btn = egui::Button::new(egui::RichText::new("▶ 변환 시작").size(16.0));
                if ui.add_sized([ui.available_width(), 32.0], btn).clicked() {
                    self.start_encoding();
                }
            });

            if self.total_jobs > 0 {
                ui.add_space(6.0);
                ui.separator();
                let overall = if self.total_jobs == 0 {
                    0.0
                } else {
                    (self.attempted_jobs as f32 + self.current_percent) / self.total_jobs as f32
                };
                ui.label(format!(
                    "전체 진행 ({}/{})",
                    self.attempted_jobs, self.total_jobs
                ));
                ui.add(egui::ProgressBar::new(overall.clamp(0.0, 1.0)).show_percentage());
                ui.label(&self.current_status);

                ui.add_space(4.0);
                egui::ScrollArea::vertical()
                    .id_salt("log_scroll")
                    .max_height(150.0)
                    .auto_shrink([false, false])
                    .stick_to_bottom(true)
                    .show(ui, |ui| {
                        for line in &self.log {
                            ui.monospace(line);
                        }
                    });
            }
            });
        });
    }
}

/// 실행 파일(exe)이 있는 폴더. 기본 출력 위치로 쓴다.
fn exe_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."))
}

/// 로컬 오디오의 출력 mp4 경로(출력 폴더 지정 시 그 폴더, 아니면 exe 폴더).
fn output_path_for(output_dir: &Option<PathBuf>, audio: &PathBuf) -> PathBuf {
    let stem = audio
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "output".to_string());
    let dir = output_dir.clone().unwrap_or_else(exe_dir);
    dir.join(format!("{stem}.mp4"))
}

/// 유튜브 결과 mp4를 저장할 폴더(지정 폴더 → exe 폴더).
fn youtube_output_dir(output_dir: &Option<PathBuf>) -> PathBuf {
    output_dir.clone().unwrap_or_else(exe_dir)
}

fn source_label(source: &JobSource) -> String {
    match source {
        JobSource::Local(p) => p
            .file_name()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default(),
        JobSource::YouTube(url) => url.clone(),
    }
}

/// 파일 이름으로 쓸 수 없는 문자를 밑줄로 바꾼다.
fn sanitize(name: &str) -> String {
    let cleaned: String = name
        .chars()
        .map(|c| match c {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '_',
            c if (c as u32) < 0x20 => '_',
            c => c,
        })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').trim();
    if trimmed.is_empty() {
        "youtube".to_string()
    } else {
        trimmed.to_string()
    }
}

fn resolve_image(src: &ImageSource, tx: &Sender<Progress>) -> anyhow::Result<PathBuf> {
    let cache_dir = crate::binaries::cache_dir()?;

    match src {
        ImageSource::Default => {
            let path = cache_dir.join("default_image.jpg");
            if !path.exists() {
                std::fs::write(&path, DEFAULT_IMAGE_BYTES)?;
            }
            Ok(path)
        }
        ImageSource::LocalFile(p) => Ok(p.clone()),
        ImageSource::Url(url) => {
            let _ = tx.send(Progress::Status(format!("이미지 다운로드 중: {url}")));
            let agent = ureq::AgentBuilder::new()
                .timeout_connect(Duration::from_secs(15))
                .timeout_read(Duration::from_secs(60))
                .build();
            let resp = agent.get(url).call()?;
            let mut buf = Vec::new();
            resp.into_reader().read_to_end(&mut buf)?;
            let ext = detect_ext(url, &buf);
            let path = cache_dir.join(format!("downloaded.{ext}"));
            std::fs::write(&path, &buf)?;
            Ok(path)
        }
    }
}

fn detect_ext(url: &str, bytes: &[u8]) -> &'static str {
    if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        return "jpg";
    }
    if bytes.starts_with(&[0x89, 0x50, 0x4E, 0x47]) {
        return "png";
    }
    if bytes.len() >= 12 && &bytes[0..4] == b"RIFF" && &bytes[8..12] == b"WEBP" {
        return "webp";
    }
    if bytes.starts_with(b"BM") {
        return "bmp";
    }
    let lower = url.to_ascii_lowercase();
    for e in ["jpg", "jpeg", "png", "webp", "bmp"] {
        if lower.contains(&format!(".{e}")) {
            return if e == "jpeg" { "jpg" } else { e };
        }
    }
    "jpg"
}

pub fn setup_fonts(ctx: &egui::Context) {
    let mut fonts = egui::FontDefinitions::default();
    let candidates = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/gulim.ttc",
    ];
    for path in candidates {
        if let Ok(data) = std::fs::read(path) {
            fonts
                .font_data
                .insert("ko".to_owned(), egui::FontData::from_owned(data));
            fonts
                .families
                .entry(egui::FontFamily::Proportional)
                .or_default()
                .insert(0, "ko".to_owned());
            fonts
                .families
                .entry(egui::FontFamily::Monospace)
                .or_default()
                .insert(0, "ko".to_owned());
            break;
        }
    }
    ctx.set_fonts(fonts);
}
