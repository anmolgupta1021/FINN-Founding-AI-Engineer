# FINN — ENAM Final Submission Checklist

## 1. Submission Metadata
- **Recipient:** `assessment@enam.com`
- **Subject Line:** `IIT Kanpur – Founding AI Engineer - 2027`
- **Deployed Production URL:** `https://finn-bay.vercel.app`
- **Cost & Ledger URL:** `https://finn-bay.vercel.app/cost`
- **Public GitHub Repo URL:** `https://github.com/anmolgupta1021/FINN-Founding-AI-Engineer`

---

## 2. Attachments & Links to Include in Email
1. Public GitHub repository URL (`https://github.com/<user>/<repo>`) — push from local `main` after final review.
2. Live deployed PWA URL: `https://finn-bay.vercel.app`
3. Architecture & Decisions Writeup (`docs/WRITEUP.md`, 900–1200 words) and Decision Log (`docs/DECISIONS.md`).
4. Exported conversation / build-history transcript log (exported cleanly after secret scan verification).

---

## 3. Mandatory Pre-Push Secret & Hygiene Verification Commands
Run these commands before `git push` (note: **never** push if any match is non-zero in tracked files or snapshots):

```bash
# 1. Scan tracked repo + git history + snapshots + ledger for Gemini / API key prefixes
git grep -F "AI""za" || echo "tracked prefix 1: 0"
git grep -F "AQ""." || echo "tracked prefix 2: 0"
git log --all -S "AI""za" --oneline
git log --all -S "AQ""." --oneline
grep -rn -E "AI""za|AQ""\.[A-Za-z0-9_-]{20,}" apps/api/data/snapshots/ .env.example || echo "snapshots clean: 0"

# 2. Verify no .env / secrets are staged
git status --short --branch

# 3. Run full backend & frontend verification suite
PYTHONPATH=apps/api apps/api/.venv/bin/pytest apps/api/tests/
apps/api/.venv/bin/ruff check apps/api/
cd apps/web && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/eslint .
```

---

## 4. Build-History Export Steps
1. Scrub any key substrings from exported logs (check for `AI""za`, `AQ"".`, and any old 8-char key prefixes):
   ```bash
   # Verify exported transcript bundle contains 0 key tokens before sharing
   grep -n -E "AI""za|AQ""\.[A-Za-z0-9_-]{20,}" <exported_build_history_file> || echo "export clean"
   ```
2. Attach or link the scrubbed build history alongside `docs/WRITEUP.md` in the email to `assessment@enam.com`.

---

## 5. Human Final Steps (Do Not Automate Secrets/Push)
- [x] Push to public repository: `https://github.com/anmolgupta1021/FINN-Founding-AI-Engineer` (remote `origin/main` tracking).
- [ ] Confirm `GEMINI_API_KEY` and `DATABASE_URL` (optional) are configured in Vercel Dashboard environment variables (never commit `.env` or `.env.local`).
- [ ] Run one final check of `https://finn-bay.vercel.app` on mobile/desktop (toggle `24h` → `7d`, inspect `DIXON`/`POLYCAB`/`HDFCBANK` vs `NAVINFLUOR`/`SYRMA`/`TITAN`, open `/cost`).
- [ ] Send email to `assessment@enam.com` with subject `IIT Kanpur – Founding AI Engineer - 2027`.
