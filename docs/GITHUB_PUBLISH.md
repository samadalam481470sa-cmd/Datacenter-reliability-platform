# Publishing this project to your own GitHub account

This project is a finished downloadable source package, **not yet a remotely created GitHub repository**. No GitHub account name or repository URL is implied by its presence in a zip.

After downloading and unzipping this project:

```bash
cd rackhelm-fleetos
python -m pip install -e ".[dev]"
pytest -q
git init
# Configure your Git author identity if needed.
git add .
git commit -m "feat: initial RackHelm FleetOS data center reliability platform"
# With GitHub CLI already authenticated:
gh repo create rackhelm-fleetos --public --source=. --remote=origin --push
```

Or create an empty repository named `rackhelm-fleetos` through GitHub and run:

```bash
git remote add origin https://github.com/YOUR_USERNAME/rackhelm-fleetos.git
git branch -M main
git push -u origin main
```

If you supply a repository URL and authorize an assistant to write to it, the full project can be committed to that repository. Do not paste GitHub tokens into chat.

The `README.md` includes **actual browser-rendered dashboard screenshots** and a disclosure of the test fixture capture technique. CI will validate Python and Docker when pushed to GitHub.