#!/usr/bin/env bash
# Refresh the mind map dataset from the live Substack sitemap,
# re-inline it into index.html, and push to GitHub.
# Vercel will auto-deploy ~30s after the push.
set -euo pipefail

cd "$(dirname "$0")"
echo "→ Working in: $(pwd)"

# 1. Pull a fresh sitemap from Substack
echo "→ Fetching sitemap..."
curl -sSL --fail "https://navnoorbawa.substack.com/sitemap.xml" -o /tmp/nb_sitemap.xml
echo "   sitemap size: $(wc -c < /tmp/nb_sitemap.xml) bytes"

# 2. Rebuild the enriched dataset
echo "→ Rebuilding data.json..."
python3 build_data.py

# 3. Re-inline data.json into index.html
echo "→ Re-inlining dataset into index.html..."
python3 - <<'PY'
import re, pathlib
html = pathlib.Path("index.html").read_text()
data = pathlib.Path("data.json").read_text().replace("</", "<\\/")
new_html, n = re.subn(
    r'(<script id="dataset"[^>]*>).*?(</script>)',
    lambda m: m.group(1) + data + m.group(2),
    html, count=1, flags=re.S,
)
if n != 1:
    raise SystemExit("ERROR: could not find <script id=\"dataset\"> block in index.html")
pathlib.Path("index.html").write_text(new_html)
print(f"   index.html now {len(new_html):,} chars")
PY

# 4. Stage, commit, push — but only if something actually changed
git add data.json index.html
if git diff --cached --quiet; then
  echo "→ No changes — nothing to deploy."
  exit 0
fi

STAMP="$(date +%Y-%m-%d)"
git commit -m "Refresh dataset ${STAMP}"
git push
echo "✓ Pushed. Vercel will redeploy in ~30s."
