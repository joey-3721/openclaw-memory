# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

## GitHub SSH

- GitHub user: `joey-3721`
- GitHub email: `lijiayi3721@gmail.com`
- Remote repo: `git@github.com:joey-3721/openclaw-memory.git`
- Local repo auto-push: enabled via `.git/hooks/post-commit`
- Behavior: after local commits in this workspace, git will try to push automatically to `origin`
- SSH key fingerprint (newly generated 2026-03-19): `SHA256:FShNKfViqidbSFMrFatLdt9WE22BTTeWgTt0SzMdnr8`
- Public key (add to GitHub → Settings → SSH keys): `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILQf5AmMKTQRsRKEgfKMfQSUU0Uz8tgRpiDVte4SLL67 lijiayi3721@gmail.com`

---

Add whatever helps you do your job. This is your cheat sheet.
