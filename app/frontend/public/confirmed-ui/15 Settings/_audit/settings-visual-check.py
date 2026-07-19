import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import pathname2url

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = Path(__file__).resolve().parent / "screenshots"

PAGES = [
    {
        "id": "01-settings-overview-v1",
        "file": ROOT / "01 Settings Overview" / "visual-drafts" / "settings-overview-v1.html",
    },
    {
        "id": "02-settings-appearance-theme-v1",
        "file": ROOT / "02 Appearance And Theme" / "visual-drafts" / "settings-appearance-theme-v1.html",
    },
    {
        "id": "03-settings-model-configuration-v1",
        "file": ROOT / "03 Model Configuration" / "visual-drafts" / "settings-model-configuration-v1.html",
    },
    {
        "id": "04-settings-current-model-health-v1",
        "file": ROOT / "04 Current Model And Health Check" / "visual-drafts" / "settings-current-model-health-v1.html",
    },
    {
        "id": "05-settings-secrets-security-v1",
        "file": ROOT / "05 Secrets And Security" / "visual-drafts" / "settings-secrets-security-v1.html",
    },
    {
        "id": "06-settings-creative-preferences-v1",
        "file": ROOT / "06 Creative Preferences" / "visual-drafts" / "settings-creative-preferences-v1.html",
    },
]

VIEWPORTS = [
    {"name": "desktop", "width": 1440, "height": 1000},
    {"name": "mobile", "width": 390, "height": 844},
]


def file_url(path: Path) -> str:
    return urljoin("file:", pathname2url(str(path)))


def collect_issues(page):
    return page.evaluate(
        """
        () => {
          const doc = document.documentElement;
          const pageOverflow = Math.max(doc.scrollWidth, document.body.scrollWidth) - window.innerWidth;
          const elementOverflow = Array.from(document.querySelectorAll("body *"))
            .filter((element) => {
              const style = window.getComputedStyle(element);
              const rect = element.getBoundingClientRect();
              if (style.display === "none" || style.visibility === "hidden" || rect.width < 8 || rect.height < 8) {
                return false;
              }
              if (style.overflowX === "auto" || style.overflowX === "scroll") {
                return false;
              }
              return element.scrollWidth - element.clientWidth > 2;
            })
            .slice(0, 12)
            .map((element) => ({
              tag: element.tagName.toLowerCase(),
              className: element.className || "",
              text: (element.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 80),
              delta: element.scrollWidth - element.clientWidth,
            }));

          return { pageOverflow, elementOverflow };
        }
        """
    )


def main():
    results = []
    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        for page_info in PAGES:
            for viewport in VIEWPORTS:
                page = browser.new_page(viewport={"width": viewport["width"], "height": viewport["height"]})
                page.goto(file_url(page_info["file"]), wait_until="networkidle")
                page.wait_for_timeout(350)
                page.screenshot(
                    path=str(SCREENSHOTS_DIR / f"{page_info['id']}-{viewport['name']}.png"),
                    full_page=True,
                )
                issues = collect_issues(page)
                results.append({"page": page_info["id"], "viewport": viewport["name"], **issues})
                page.close()
        browser.close()
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
