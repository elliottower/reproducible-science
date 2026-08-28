// Two Rust PDF text layers behind one CLI, so the benchmark harness can call either the same
// way it calls pdftotext: `pdfrs <mode> <file.pdf>` prints the text to stdout.
//
//   extract   pdf-extract, which has its own text-positioning layer over lopdf's object model
//   lopdf     lopdf's own Document::extract_text, the object model with no layout layer
use std::env;
use std::io::Write;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: pdfrs <extract|lopdf> <file.pdf>");
        std::process::exit(2);
    }
    let mode = &args[1];
    let path = &args[2];

    let text = match mode.as_str() {
        "extract" => match pdf_extract::extract_text(path) {
            Ok(t) => t,
            Err(e) => {
                eprintln!("pdf-extract failed: {e}");
                std::process::exit(1);
            }
        },
        "lopdf" => {
            let doc = match lopdf::Document::load(path) {
                Ok(d) => d,
                Err(e) => {
                    eprintln!("lopdf load failed: {e}");
                    std::process::exit(1);
                }
            };
            let pages: Vec<u32> = doc.get_pages().keys().copied().collect();
            match doc.extract_text(&pages) {
                Ok(t) => t,
                Err(e) => {
                    eprintln!("lopdf extract_text failed: {e}");
                    std::process::exit(1);
                }
            }
        }
        other => {
            eprintln!("unknown mode: {other}");
            std::process::exit(2);
        }
    };
    let out = std::io::stdout();
    let mut lock = out.lock();
    let _ = lock.write_all(text.as_bytes());
}
