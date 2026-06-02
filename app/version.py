"""Single source of truth for the app version and its GitHub home.

The release CI overwrites APP_VERSION at build time so every pushed release gets
a unique, increasing version (e.g. 0.6.<build-number>). The value here is the
local/dev fallback. The in-app updater compares this against the latest GitHub
release to decide whether to offer a "click to update".
"""

APP_VERSION = "0.6.2"

# Public GitHub repository that hosts the releases the in-app updater pulls from.
GITHUB_OWNER = "SharkMenCyber"
GITHUB_REPO = "prompt-optimizer-openrouter"
