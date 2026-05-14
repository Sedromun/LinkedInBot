"""
Bot message templates — all in English.
"""

# ── /start ────────────────────────────────────────────────────────────────────

WELCOME_NEW = """\
👋 Hey, {name}!

I'm a bot that writes and publishes LinkedIn posts on autopilot.

<b>How it works:</b>
1️⃣ Connect your LinkedIn — takes 30 seconds
2️⃣ Pick topics you're interested in (AI, ML, Crypto…)
3️⃣ Every day at 6 PM I'll suggest a topic for a new post
4️⃣ For $1 I research the topic, write the post, generate infographic images and publish it — all from your account

<b>Starting balance:</b> ${balance:.2f} ({posts} posts)
<b>Price per post:</b> ${cost:.2f}

Let's start by connecting LinkedIn 👇
"""

WELCOME_AUTHORIZED = """\
👋 Hey, {name}!

<b>LinkedIn connected</b> ✅
<b>Balance:</b> ${balance:.2f} ({posts} posts)

Hit "Generate post" or wait for the daily reminder at 6 PM 👇
"""

# ── LinkedIn OAuth ─────────────────────────────────────────────────────────────

OAUTH_INSTRUCTIONS = """\
🔗 <b>Connect LinkedIn</b>

Click the link below, log into LinkedIn and click "Allow".
I'll save your token automatically and send you a confirmation here.

<a href="{url}">👉 Connect LinkedIn</a>

<i>We never see your password — this is standard OAuth, just like "Sign in with Google".</i>
<i>Token is valid for 60 days.</i>
"""

OAUTH_SUCCESS_MOCK = """\
🧪 <b>DEV mode:</b> LinkedIn "connected" (mock token).

Posts will be generated for real (Gemini + images) but <b>not published</b> to LinkedIn.

You can now:
• /generate — try generating a post
• /interests — choose your topics
• /balance — check balance
"""

OAUTH_SUCCESS = """\
✅ <b>LinkedIn connected successfully!</b>

I can now publish posts on your behalf.

Next step — choose your topics:
👉 /interests

Or hit /generate right now!
"""

OAUTH_ALREADY_DONE = """\
✅ LinkedIn is already connected.

If you want to reconnect, contact the admin.
"""

NOT_AUTHORIZED = """\
🔗 You need to connect LinkedIn before generating posts.

Go to /start and choose "Connect LinkedIn".
"""

# ── Interests ──────────────────────────────────────────────────────────────────

CHOOSE_INTERESTS = """\
🎯 <b>Choose your topics</b>

I'll use these to suggest post ideas. You can pick multiple.
When you're done — hit "Done".
"""

INTERESTS_SAVED = """\
✅ Saved! Your topics: {labels}

Now:
• /generate — create a post right now
• Or wait for the daily reminder at 6 PM
"""

INTERESTS_EMPTY = "⚠️ Please select at least one topic."

# ── Balance / payments ────────────────────────────────────────────────────────

BALANCE_INFO = """\
💰 <b>Balance:</b> ${balance:.2f}
<b>Price per post:</b> ${cost:.2f}
<b>Regenerate text:</b> ${regen:.2f}
<b>Posts available:</b> {posts}

Hit "Top up" to add funds.
"""

TOPUP_PROMPT = """\
💵 How much would you like to add?
"""

TOPUP_SUCCESS = """\
✅ Added ${amount:.2f} to your balance.
<b>Current balance:</b> ${balance:.2f}
"""

INSUFFICIENT_FUNDS = """\
😔 <b>Insufficient funds.</b>

Required: ${need:.2f}
Balance: ${balance:.2f}

Go to /balance → "Top up" to add funds.
"""

# ── Generate flow ─────────────────────────────────────────────────────────────

GENERATE_PROMPT = """\
🎯 <b>What should we write about?</b>

Type a topic (e.g. <i>"GPU inference cost optimization"</i>)
or hit "🎲 Pick from my interests".
"""

TOPIC_SUGGESTION = """\
🎲 <b>How about this topic:</b>

<i>"{topic}"</i>

Want to generate a post on this?
"""

GENERATING_TEXT = """\
⏳ <b>Writing the post…</b>

Topic: <i>"{topic}"</i>

Gemini is searching Google for fresh data and writing the post — ~20–40 sec.
"""

TEXT_PREVIEW_HEADER = """\
📝 <b>Text is ready! Here's what I came up with:</b>
"""

TEXT_PREVIEW_FOOTER = """\

<i>Characters: {chars}</i>

Looks good? I'll generate the images next.
Or regenerate the text for ${regen:.2f}.
"""

GENERATING_IMAGES = """\
🎨 <b>Text approved! Drawing infographics…</b>

Generating {count} {noun} — ~30–60 sec.
"""

FINAL_PREVIEW_HEADER = """\
✨ <b>Post is ready! Publish to LinkedIn?</b>
"""

FINAL_PREVIEW_FOOTER = """\

💰 Will be charged: ${cost:.2f} (remaining: ${balance:.2f})
"""

PUBLISHED = """\
🚀 <b>Published to LinkedIn!</b>

🔗 <a href="https://www.linkedin.com/feed/update/{post_id}/">View on LinkedIn</a>

💸 Charged: ${cost:.2f} · Balance: ${balance:.2f}
"""

PUBLISHED_MOCK = """\
✅ <b>Post generated</b> (DEV mode — not sent to LinkedIn)

mock post_id: <code>{post_id}</code>

💸 Charged: ${cost:.2f} · Balance: ${balance:.2f}
"""

PUBLISH_CANCELLED = """\
❌ Cancelled. Post not published, nothing charged.

/generate to start over.
"""

REGEN_CHARGED = """\
🔄 Charged ${regen:.2f} for regeneration. Writing a new text…
"""

GENERATION_FAILED = """\
❌ <b>Generation failed</b>

{error}

Nothing was charged. Try again: /generate
"""

# ── Daily nudge ───────────────────────────────────────────────────────────────

DAILY_NUDGE = """\
🔔 <b>Time for a new post!</b>

Here's a topic from your interests: <i>{topics}</i>

💰 Balance: ${balance:.2f} ({posts} posts available)

👉 /generate
"""

# ── Settings ──────────────────────────────────────────────────────────────────

SETTINGS_INFO = """\
⚙️ <b>Settings</b>

Reminders: <b>{daily}</b>
Time: <b>{time}</b>
Days: <b>{days}</b>
Topics: {interests}

<i>All times are in server local time.</i>
"""

# ── Notification time / days pickers ─────────────────────────────────────────

PICK_HOUR = """\
⏰ <b>Pick the hour</b>

Current: <b>{current}</b>
"""

PICK_MINUTE = """\
⏰ <b>Pick the minutes</b>

Hour selected: <b>{hour:02d}:??</b>
"""

TIME_SAVED = """\
✅ Notification time saved: <b>{time}</b>

I'll ping you at this time on your selected days.
"""

PICK_DAYS = """\
📅 <b>Pick the days</b>

Toggle the days you want reminders on, then hit Save.
Currently: <b>{current}</b>
"""

DAYS_SAVED = """\
✅ Notification days saved: <b>{days}</b>
"""

DAYS_EMPTY = "⚠️ Please select at least one day."

