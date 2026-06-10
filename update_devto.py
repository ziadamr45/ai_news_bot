#!/usr/bin/env python3
"""
Update dev.to articles with the latest content from blog-data.ts.

This script:
1. Parses blog-data.ts to extract article content (using regex)
2. Maps slugs to dev.to article IDs (AR and EN)
3. Replaces local image paths (/blog/...) with full URLs
4. Updates each article via the dev.to API (using curl) with proper delays
"""

import json
import re
import subprocess
import time
import sys
import os
import tempfile

# Configuration
DEVTO_API_KEY = "gDaeyTKVUk8rzW1HXVriyDYR"
DEVTO_API_BASE = "https://dev.to/api/articles"
IMAGE_BASE_URL = "https://ziadamrme.vercel.app"
BLOG_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ziadamrme", "src", "lib", "blog-data.ts"
)
DELAY_BETWEEN_CALLS = 2  # seconds

# Mapping of dev.to article IDs to (blog slug, language)
ARTICLES = {
    # Arabic articles
    "3841338": ("building-modern-web-apps", "ar"),
    "3841359": ("real-time-apps-socketio", "ar"),
    "3841366": ("secure-location-sharing", "ar"),
    "3841373": ("building-arabic-web-apps", "ar"),
    "3841378": ("web-security-lessons", "ar"),
    "3841386": ("tailwind-css-journey", "ar"),
    "3841385": ("database-journey", "ar"),
    "3737004": ("pwa-journey", "ar"),
    "3737023": ("web-push-notifications", "ar"),
    "3737042": ("building-news-aggregator", "ar"),
    "3737078": ("building-developer-portfolio", "ar"),
    "3841390": ("typescript-type-safety", "ar"),
    "3841399": ("database-performance-postgresql", "ar"),
    "3841408": ("progressive-web-apps", "ar"),
    "3841504": ("ai-agents-future", "ar"),
    # English articles
    "3841339": ("building-modern-web-apps", "en"),
    "3841361": ("real-time-apps-socketio", "en"),
    "3841372": ("secure-location-sharing", "en"),
    "3841376": ("building-arabic-web-apps", "en"),
    "3841382": ("web-security-lessons", "en"),
    "3841381": ("tailwind-css-journey", "en"),
    "3841387": ("database-journey", "en"),
    "3737006": ("web-push-notifications", "en"),
    "3737040": ("building-news-aggregator", "en"),
    "3737077": ("building-developer-portfolio", "en"),
    "3841395": ("typescript-type-safety", "en"),
    "3841403": ("database-performance-postgresql", "en"),
    "3841411": ("progressive-web-apps", "en"),
    "3841505": ("ai-agents-future", "en"),
    "3841514": ("ai-web-development", "en"),
}


def parse_blog_data():
    """Parse blog-data.ts using regex to extract content for each slug."""
    print("  Reading blog-data.ts...")
    with open(BLOG_DATA_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    blog_data = {}

    # Find all slug entries
    slug_pattern = r'slug:\s*"([^"]+)"'
    slugs = re.findall(slug_pattern, content)
    print(f"  Found {len(slugs)} slugs: {slugs}")

    for slug in slugs:
        # Find the position of this slug in the content
        slug_pos = content.find(f'slug: "{slug}"')
        if slug_pos == -1:
            continue

        # Find the content block after this slug
        content_start = content.find("content: {", slug_pos)
        if content_start == -1:
            continue

        # Find Arabic content (between ar: ` and the closing `)
        ar_marker = "ar: `"
        ar_start = content.find(ar_marker, content_start)
        if ar_start == -1:
            continue
        ar_start += len(ar_marker)

        # Find the end of the Arabic template literal
        ar_end = _find_closing_backtick(content, ar_start)
        if ar_end == -1:
            print(f"  ⚠ Could not find end of Arabic content for '{slug}'")
            continue

        ar_content = content[ar_start:ar_end]

        # Find English content
        en_marker = "en: `"
        en_start = content.find(en_marker, ar_end)
        if en_start == -1:
            continue
        en_start += len(en_marker)

        en_end = _find_closing_backtick(content, en_start)
        if en_end == -1:
            print(f"  ⚠ Could not find end of English content for '{slug}'")
            continue

        en_content = content[en_start:en_end]

        blog_data[slug] = {
            "ar": ar_content,
            "en": en_content
        }

    return blog_data


def _find_closing_backtick(content, start):
    """Find the closing backtick for a template literal."""
    i = start
    while i < len(content):
        if content[i] == '`':
            return i
        i += 1
    return -1


def replace_image_paths(content):
    """Replace /blog/ image paths with full URLs in markdown images."""
    return content.replace("](/blog/", f"]({IMAGE_BASE_URL}/blog/")


def update_devto_article(article_id, body_markdown):
    """Update a single dev.to article via the API using curl."""
    url = f"{DEVTO_API_BASE}/{article_id}"

    payload = json.dumps({
        "article": {
            "body_markdown": body_markdown
        }
    })

    # Write payload to a temp file to avoid shell escaping issues with large content
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        f.write(payload)
        temp_path = f.name

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-w", "\nHTTP_CODE:%{http_code}",
                "-X", "PUT", url,
                "-H", f"api-key: {DEVTO_API_KEY}",
                "-H", "Content-Type: application/json",
                "-d", f"@{temp_path}"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )

        output = result.stdout

        # Parse the HTTP code from the last line
        lines = output.rsplit("\nHTTP_CODE:", 1)
        if len(lines) == 2:
            body = lines[0]
            http_code = int(lines[1].strip())
        else:
            body = output
            http_code = 0

        if http_code == 200:
            try:
                response_data = json.loads(body)
                title = response_data.get("title", "Unknown")
                return True, title, http_code
            except json.JSONDecodeError:
                return True, "Updated", http_code
        else:
            # Try to extract error message
            try:
                error_data = json.loads(body)
                error_msg = error_data.get("error", body[:200])
            except:
                error_msg = body[:200]
            return False, error_msg, http_code

    except subprocess.TimeoutExpired:
        return False, "Request timed out", 0
    except Exception as e:
        return False, str(e), 0
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    print("=" * 60)
    print("Dev.to Article Updater")
    print("=" * 60)
    print()

    # Step 1: Extract blog data
    print("Step 1: Parsing blog-data.ts...")
    blog_data = parse_blog_data()

    if not blog_data:
        print("\n❌ Could not parse blog data. Exiting.")
        sys.exit(1)

    print(f"  ✓ Successfully parsed {len(blog_data)} blog posts")

    # Verify all required slugs are present
    required_slugs = set(slug for slug, lang in ARTICLES.values())
    missing_slugs = required_slugs - set(blog_data.keys())
    if missing_slugs:
        print(f"  ⚠ Missing slugs in blog data: {missing_slugs}")

    # Show content lengths
    for slug in sorted(blog_data.keys()):
        ar_len = len(blog_data[slug]["ar"])
        en_len = len(blog_data[slug]["en"])
        print(f"    {slug}: AR={ar_len} chars, EN={en_len} chars")

    print()

    # Step 2: Update each article
    print("Step 2: Updating dev.to articles...")
    print(f"Total articles to update: {len(ARTICLES)}")
    print()

    success_count = 0
    fail_count = 0
    skip_count = 0
    results = []

    for i, (article_id, (slug, lang)) in enumerate(ARTICLES.items()):
        lang_label = lang.upper()
        print(f"[{i+1}/{len(ARTICLES)}] Article {article_id} ({slug} - {lang_label})...")

        # Get content for this slug and language
        if slug not in blog_data:
            print(f"  ⚠ Slug '{slug}' not found in blog data. Skipping.")
            skip_count += 1
            results.append((article_id, slug, lang, "skip", "Slug not found"))
            continue

        content = blog_data[slug].get(lang, "")
        if not content:
            print(f"  ⚠ No {lang_label} content for slug '{slug}'. Skipping.")
            skip_count += 1
            results.append((article_id, slug, lang, "skip", "No content"))
            continue

        # Replace image paths
        content = replace_image_paths(content)

        # Verify image path replacement
        img_count = content.count(f"{IMAGE_BASE_URL}/blog/")
        if img_count > 0:
            print(f"  Found {img_count} image(s) with full URLs")

        # Update via API
        success, message, status_code = update_devto_article(article_id, content)

        if success:
            print(f"  ✓ Updated successfully (HTTP {status_code}) - '{message[:60]}'")
            success_count += 1
            results.append((article_id, slug, lang, "success", f"HTTP {status_code}"))
        else:
            msg_short = str(message)[:100]
            print(f"  ✗ Failed (HTTP {status_code}): {msg_short}")
            fail_count += 1
            results.append((article_id, slug, lang, "fail", f"HTTP {status_code}: {msg_short}"))

        # Delay between calls (except for the last one)
        if i < len(ARTICLES) - 1:
            time.sleep(DELAY_BETWEEN_CALLS)

    # Step 3: Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total articles processed: {len(ARTICLES)}")
    print(f"Successfully updated: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Skipped: {skip_count}")
    print()

    if fail_count > 0 or skip_count > 0:
        print("Issues:")
        for article_id, slug, lang, status, message in results:
            if status != "success":
                label = "SKIP" if status == "skip" else "FAIL"
                print(f"  [{label}] {article_id} ({slug} - {lang.upper()}): {message}")

    print()
    if fail_count == 0 and skip_count == 0:
        print("🎉 All articles updated successfully!")
    else:
        print("Done with some issues. See above for details.")


if __name__ == "__main__":
    main()
