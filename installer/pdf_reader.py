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
import stat
from file_transfer import contained, open_source

SWIFT = r'''
import Foundation
import PDFKit
import Vision
import AppKit

let descriptor = Int32(CommandLine.arguments[1])!
let useOCR = CommandLine.arguments[2] == "ocr"
let limit = Int(CommandLine.arguments[3]) ?? 12
let first = max(0, (Int(CommandLine.arguments[4]) ?? 1) - 1)
let charLimit = Int(CommandLine.arguments[5]) ?? 24000
let data = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false).readData(ofLength: 35_000_001)
guard data.count <= 35_000_000, let pdf = PDFDocument(data: data) else {
  fputs("Cannot open PDF or PDF requires a password.\n", stderr); exit(2)
}
guard !pdf.isLocked else { fputs("Encrypted PDF requires manual unlocking.\n", stderr); exit(2) }
let count = pdf.pageCount
guard first < count else { fputs("Start page exceeds page count.\n", stderr); exit(2) }
var pages: [[String: Any]] = []
var used = 0
var next = first
for n in first..<min(count, first + limit) {
  guard let page = pdf.page(at: n) else { continue }
  var text = page.string ?? ""
  var method = "embedded"
  var ocrError = false
  if useOCR {
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
        let recognized = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
          text = recognized; method = "ocr"
        } else {
          let extra = recognized.split(separator: "\n").filter { !text.localizedCaseInsensitiveContains(String($0)) }.joined(separator: "\n")
          if !extra.isEmpty { text += "\n[Additional OCR text]\n" + extra; method = "embedded+ocr" }
        }
      } catch { ocrError = true }
    }
  }
  if used > 0 && used + min(text.count, 12000) > charLimit { break }
  let budget = min(12000, charLimit - used)
  let clipped = String(text.prefix(budget))
  pages.append(["page": n + 1, "text": clipped, "truncated": text.count > budget,
                "method": method, "ocr_error": ocrError, "empty": text.isEmpty])
  used += clipped.count
  next = n + 1
}
let result: [String: Any] = ["page_count": count, "pages": pages, "limited": next < count,
                           "next_page": next < count ? (next + 1) as Any : NSNull(), "start_page": first + 1]
let bytes = try! JSONSerialization.data(withJSONObject: result)
FileHandle.standardOutput.write(bytes)
'''


def read_pdf(path, root, *, ocr=False, max_pages=12, start_page=1, max_chars=24000):
    root = Path(root).resolve(strict=True)
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    if source.is_symlink() or not source.absolute().is_relative_to(root):
        raise ValueError("PDF must be a regular file inside the selected project")
    relative = source.absolute().relative_to(root)
    source = contained(root, relative)
    if not source.is_file() or source.suffix.lower() != ".pdf" or source.stat().st_size > 35_000_000:
        raise ValueError("PDF must be a local PDF under 35 MB")
    with source.open("rb") as file:
        if file.read(5) != b"%PDF-":
            raise ValueError("Not a PDF file")
    if type(max_pages) is not int or not 1 <= max_pages <= 40:
        raise ValueError("PDF page budget must be 1–40")
    if type(start_page) is not int or start_page < 1 or type(max_chars) is not int or not 1000 <= max_chars <= 48000:
        raise ValueError('Invalid start page or text budget')
    if not Path("/usr/bin/swift").is_file():
        raise RuntimeError("Apple Swift toolchain is unavailable")
    with tempfile.TemporaryDirectory(prefix="local-ai-pdf-") as temporary:
        script = Path(temporary) / "pdf_extract.swift"
        script.write_text(SWIFT)
        source_fd = open_source(root, relative)
        try:
            info = os.fstat(source_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 35_000_000:
                raise ValueError('Unsafe PDF source')
            result = subprocess.run(["/usr/bin/swift", str(script), str(source_fd), "ocr" if ocr else "text",
                                     str(max_pages), str(start_page), str(max_chars)], capture_output=True, text=True,
                                    timeout=180, check=True, pass_fds=(source_fd,), env={k: v for k, v in os.environ.items()
                                                                  if k in {"HOME", "PATH", "TMPDIR"}})
        except subprocess.TimeoutExpired:
            raise RuntimeError('PDF extraction timed out. Request fewer pages.') from None
        except subprocess.CalledProcessError:
            raise RuntimeError('PDF cannot be read. It may be corrupt, encrypted, or outside the requested page range.') from None
        finally:
            os.close(source_fd)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument('--start-page', type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(read_pdf(args.pdf, args.root, ocr=args.ocr, max_pages=args.max_pages, start_page=args.start_page),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

