"""Conservative PDF text extraction with optional Apple Vision OCR.

Local PDFKit/Vision via /usr/bin/swift. No cloud service, network access,
install-time LLM or always-running OCR daemon.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

SWIFT = r'''
import Foundation
import PDFKit
import Vision
import AppKit

let path = CommandLine.arguments[1]
let useOCR = CommandLine.arguments[2] == "ocr"
let limit = Int(CommandLine.arguments[3]) ?? 12
guard let pdf = PDFDocument(url: URL(fileURLWithPath: path)) else {
  fputs("Cannot open PDF or PDF requires a password.\n", stderr); exit(2)
}
let count = pdf.pageCount
var pages: [[String: Any]] = []
for n in 0..<min(count, limit) {
  guard let page = pdf.page(at: n) else { continue }
  var text = page.string ?? ""
  if text.trimmingCharacters(in: .whitespacesAndNewlines).count < 16 && useOCR {
    let rect = page.bounds(for: .mediaBox)
    let scale = min(2.0, 1800.0 / max(1.0, max(rect.width, rect.height)))
    let pxW = max(1, Int(rect.width * scale))
    let pxH = max(1, Int(rect.height * scale))
    guard pxW * pxH <= 4_000_000 else { continue }
    let img = NSImage(size: NSSize(width: pxW, height: pxH))
    img.lockFocus()
    if let ctx = NSGraphicsContext.current?.cgContext {
      ctx.saveGState(); ctx.scaleBy(x: scale, y: scale); page.draw(with: .mediaBox, to: ctx); ctx.restoreGState()
    }
    img.unlockFocus()
    if let data = img.tiffRepresentation,
       let rep = NSBitmapImageRep(data: data),
       let cg = rep.cgImage {
      let request = VNRecognizeTextRequest()
      request.recognitionLevel = .accurate
      request.usesLanguageCorrection = true
      let handler = VNImageRequestHandler(cgImage: cg)
      do {
        try handler.perform([request])
        text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
      } catch { }
    }
  }
  pages.append(["page": n + 1, "text": String(text.prefix(12000)), "truncated": text.count > 12000])
}
let result: [String: Any] = ["page_count": count, "pages": pages, "limited": count > limit]
let bytes = try! JSONSerialization.data(withJSONObject: result)
FileHandle.standardOutput.write(bytes)
'''


def read_pdf(path, root, *, ocr=False, max_pages=12):
    root = Path(root).resolve(strict=True)
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    if source.is_symlink() or not source.resolve(strict=True).is_relative_to(root):
        raise ValueError("PDF must be a regular file inside the selected project")
    source = source.resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != ".pdf" or source.stat().st_size > 35_000_000:
        raise ValueError("PDF must be a local PDF under 35 MB")
    with source.open("rb") as file:
        if file.read(5) != b"%PDF-":
            raise ValueError("Not a PDF file")
    if not 1 <= max_pages <= 40:
        raise ValueError("PDF page budget must be 1–40")
    if not Path("/usr/bin/swift").is_file():
        raise RuntimeError("Apple Swift toolchain is unavailable")
    with tempfile.TemporaryDirectory(prefix="local-ai-pdf-") as temporary:
        script = Path(temporary) / "pdf_extract.swift"
        script.write_text(SWIFT)
        result = subprocess.run(["/usr/bin/swift", str(script), str(source), "ocr" if ocr else "text",
                                 str(max_pages)], capture_output=True, text=True,
                                timeout=180, check=True, env={k: v for k, v in os.environ.items()
                                                              if k in {"HOME", "PATH", "TMPDIR"}})
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--max-pages", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(read_pdf(args.pdf, args.root, ocr=args.ocr, max_pages=args.max_pages),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
