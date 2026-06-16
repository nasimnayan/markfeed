# Deploying MarkFeed (free + private)

MarkFeed is heavy (Tesseract binary + PaddleOCR model + long-running OCR), so it
**cannot** run on serverless hosts (Vercel/Netlify/Cloudflare). The best **free**
option is **Hugging Face Spaces (Docker SDK)**, set to **Private**.

> ⚠️ Security: MarkFeed has **no login**, and the "Recent conversions" list is
> shared by anyone who can open the page. Keep the Space **Private** (only your
> Hugging Face account can open it), or add a password before making it public.
> For *zero* data ever leaving your control, run it locally and share over
> Tailscale instead of hosting it.

---

## Part A — Put the code on GitHub (one time)

You already have a git repo. From the project folder:

```bash
# 1. (Optional) rename the default branch shown on GitHub
git add -A
git commit -m "MarkFeed: live compare, 10-job history cap, Docker deploy"

# 2. Create an EMPTY repo on github.com (no README), then point this repo at it:
git remote set-url origin https://github.com/<your-username>/markfeed.git
#   (if there is no remote yet, use:  git remote add origin <url>)

git push -u origin main
```

Double-check that **`chemistry-1.pdf`, `jobs/`, and `output/` are NOT pushed** —
`.gitignore` already excludes them. Run `git status` and confirm they don't appear.

---

## Part B — Deploy to Hugging Face Spaces (free, private)

1. Make a free account at <https://huggingface.co>.
2. Click your avatar → **New Space**.
   - **Owner**: you
   - **Space name**: `markfeed`
   - **License**: your choice
   - **Select the SDK**: **Docker** → **Blank**
   - **Visibility**: **Private**  ✅ (important — see the security note above)
3. Create the Space. It gives you a git URL like
   `https://huggingface.co/spaces/<user>/markfeed`.
4. Push your code to the Space. Two easy ways:

   **Option 1 — push directly (simplest):**
   ```bash
   git remote add space https://huggingface.co/spaces/<user>/markfeed
   git push space main
   ```
   When asked for a password, paste a Hugging Face **access token** (create one at
   Settings → Access Tokens, role: *write*).

   **Option 2 — auto-sync from GitHub (set & forget):** add the GitHub Action in
   Part C so every `git push` to GitHub redeploys the Space automatically.

5. The Space starts building from the `Dockerfile`. First build takes several
   minutes (it installs Tesseract + PaddlePaddle). When it finishes, open the
   Space URL — MarkFeed loads. Because the front-matter sets `app_port: 7860`,
   no extra config is needed.

That's it. Uploads, conversion, and the **live compare** all run inside your
private Space. The recent-jobs history auto-caps at the last 10.

---

## Part C — (Optional) Auto-deploy from GitHub

Create `.github/workflows/deploy-space.yml`:

```yaml
name: Sync to Hugging Face Space
on:
  push:
    branches: [main]
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: Push to Hugging Face
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
        run: |
          git push https://user:$HF_TOKEN@huggingface.co/spaces/<user>/markfeed main --force
```

Then in GitHub: **Settings → Secrets and variables → Actions → New repository
secret**, name `HF_TOKEN`, value = your Hugging Face write token. Now every push
to GitHub `main` redeploys the Space.

---

## Notes & limits on the free tier

- **Sleep:** free Spaces sleep after ~48h idle and wake on the next visit (cold
  start takes a bit while the model reloads).
- **Storage is ephemeral:** the `jobs/` folder resets when the Space rebuilds.
  That's fine — conversions are temporary and history is capped at 10 anyway.
- **RAM:** free CPU Spaces give ~16 GB, enough for the PaddleOCR layout model.
  If you ever hit memory limits, convert with "Extract diagrams & tables" **off**
  (plain Tesseract is much lighter).
- **Other hosts:** the same `Dockerfile` works on Render, Fly.io, Railway, or any
  Docker VPS. Their free tiers have far less RAM (512 MB) and will struggle with
  layout mode — Hugging Face is the most reliable free choice.

## Most secure alternative (no hosting)

Run locally (`python run.py`) and expose it only to your own devices with
[Tailscale](https://tailscale.com) (free). Your documents then never leave your
machine — the strongest "no data leak" setup.
