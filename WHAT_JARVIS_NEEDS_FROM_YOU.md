# What Jarvis needs from you (one-time setup)

Everything below happens **on your PC** — nothing is sent to anyone.

## 1. Log in to each freelance platform — once
Open **Freelance ▸ Auto Mode ▸ STEP 0 — Platform Logins** and press **LOGIN**
next to each platform you use. A browser window opens; sign in normally
(captcha/2FA included) and close the window. Jarvis keeps that session in its
own browser profile (`backend/browser-profile`) and reuses it for scanning,
form-filling, and bid submission from then on.

**Do not paste passwords into any chat.** If you want Jarvis to pre-fill the
login forms for you, save credentials in the **Credential Vault** on the same
card — they are encrypted with a key that never leaves your machine
(`backend/vault.key`), and the API only ever shows masked usernames.

## 2. Fill your profile — once
Same page, **STEP 2**: name, skills, hourly rate, portfolio highlights.
This is injected into every proposal the AI writes, which is what makes the
proposals specific instead of generic.

## 3. Decide the autonomy level
- Default: Jarvis scans → scores → writes a proposal for every good job →
  queues them. You press **✓ APPROVE + SUBMIT** (that's your "yes").
- Tick **Full auto-submit** in the profile card if you want Jarvis to bid
  without asking.

## 4. Turn on reply monitoring (optional)
Set the settings key `monitor_inbox` to `on` (Settings page) and Jarvis sweeps
your Freelancer inbox every 30 minutes; Pulse notifies you when a client
replies to a proposal.

## 5. Better AI (optional but recommended, 16GB RAM)
```
ollama pull qwen2.5:3b        # better reasoning than qwen2.5:0.5b
ollama pull llava:7b          # true screenshot understanding for vision
pip install cryptography      # enables the credential vault
```

That's it. No logins in chat, no other files needed.
