# Voice bible — stoic quotes channel

Reference doc for script generation. Paste this whole file into the LLM prompt alongside the chosen quote from `stoic_quotes_database.csv`.

## Tone

- A father speaking directly to his son. Not a lecture, not a quote card read aloud — this is advice given in confidence, one-on-one.
- The father is the wise one. He's lived this. The words are his — no citing, no naming a philosopher, no "a wiser man than me said." The wisdom traces back to a real source in the database, but the son never hears that; he only hears his father.
- Warm but firm. Not soft self-help, not hype. The warmth comes from the relationship, not from being gentle about the truth.
- Every script opens directly with the seed quote spoken word for word (no name attached). The father speaks with the warmth, authority, and quiet confidence of a father speaking to his son. Address terms like "son" may be used naturally in the body of the script if appropriate, but are not required as a fixed opening word.
- Short, declarative sentences, the way a father talks when he actually means something — not a performance, not a TED talk.
- No rhetorical questions stacked back to back. One is fine, three is a TikTok-guru tic.
- Present tense where possible.
- Silence and restraint read as confidence. Don't over-explain — trust the son (and the viewer) to sit with it, the way a real father trusts his kid to get it without spelling out every word.
- Reference point: a father who doesn't say much, but when he does, it matters. Not a hype coach, not a therapist voice.

## Script structure

Every script follows this four-beat skeleton. Total target: 40-45 seconds spoken.

| Beat | Time | Purpose |
|---|---|---|
| Hook | 0-3s | The seed quote spoken word for word (no name attached) — opens cleanly and directly without a fixed literal prefix. This is the one place the original wording appears exactly as written in the database. On-screen text matches voiceover exactly. |
| Context | 3-15s | The father starts paraphrasing the quote into his own words and grounds it in his own experience or observation — no naming a source, just his own retelling of what that line means. |
| Application | 15-35s | What the father is actually telling his son to do, today, in his own words. Concrete, not vague. This is the instruction a son would actually remember. |
| CTA | 35-40s | Either a follow prompt framed as "more of this" or a direct question — MUST end with the word "because..." (or "because") to create an addictive rewatch loop that seamlessly flows directly back into the opening hook. |

Rules for each beat:
- **Hook**: always opens directly with the seed quote spoken word for word from the database — no name attached, no "someone once said," no mandatory "Son," prefix, just the line itself in the father's voice. Everything after the hook is the father paraphrasing and unpacking that line in his own words.
- **Context**: the father grounds the idea in his own experience or observation — no naming a source, no "someone once said." One personal-sounding detail max, only if it strengthens the point — otherwise skip it, don't pad.
- **Application**: must be doable today, phrased as instruction from father to son, not generic advice to "the viewer." Say "do this" the way a dad would, not "here's a tip."
- **CTA**: MUST end with the word **"because..."** (or "because") to prompt an immediate rewatch loop back to the opening hook.

## Target word count

- 40-45 seconds at natural spoken pace (~2.3-2.5 words/second — slower than average, a father doesn't rush what matters) = **95-110 words total**.
- Rough beat allocation: Hook 8-12 words, Context 25-35 words, Application 40-50 words, CTA 10-15 words.
- If a script comes in over 115 words, cut from Context first, never from Application — the instruction is the part the son (and the viewer) actually needs to carry away.

## Banned phrases

Avoid these — they're either AI-generation tells, overused stoic-content clichés, or break the father-son intimacy:

- "In today's fast-paced world"
- "Let that sink in"
- "This hits different"
- "Ancient wisdom for modern problems" (or any variant)
- "ready to unlock/unleash your potential"
- "at the end of the day"
- "here's the thing"
- "game changer" / "life changing"
- "in a world where..."
- "the secret that no one tells you"
- Any sentence starting with "Imagine if..." as a hook opener
- "Listen up" or "listen closely" as an opener — too performative, a real father doesn't announce he's about to say something important
- Over-explaining the philosopher's biography — the father isn't giving a history lesson, he's giving advice
- Ending every CTA with "trust me" or "you won't regret it"
- Calling the son "kid," "buddy," or "champ" — keep address terms natural and subtle, never overused

## Quote accuracy rule

The hook line must match the seed quote from `stoic_quotes_database.csv` word for word (light trimming of dialogue tags like "my dear Lucilius" is fine, but the core wording must not be altered). Everything after the hook is the father paraphrasing that same quote into his own words — no name attached, ever. The paraphrase must preserve the quote's actual meaning; if it drifts, regenerate rather than ship it.

**Long quotes**: for quotes tagged `long` in the database (and any `medium` quote that runs past ~15 words), don't force the entire line into the 3-second hook. Trim to the single punchiest clause — the one sentence or fragment that carries the full weight of the idea on its own — and speak that verbatim as the hook. The rest of the quote's meaning still gets covered, just folded into the Context/Application beats in the father's own words rather than recited. Never paraphrase the clause used in the hook itself; the trim must be a cut, not a rewrite. If no single clause under ~12 words can stand alone and still make sense, pick a different quote from the same theme instead of forcing it.

## Example script (for LLM few-shot reference)

**Quote:** "There are more things, Lucilius, likely to frighten us than there are to crush us; we suffer more often in imagination than in reality." — Seneca, Letters to Lucilius, Letter 13 (theme: fear)

> There are more things likely to frighten us than there are to crush us. We suffer more in imagination than in reality.
>
> I learned that the hard way, lying awake over things that never came. You build the whole disaster in your head before it's even had the chance to be real.
>
> Next time your chest gets tight over something, ask yourself one question. Has it actually happened? Not might it. Has it. Most of the time the answer's no. You're not fighting reality. You're fighting a story you made up.
>
> What's one thing you've been carrying that hasn't even happened yet? Tell me, because...

(97 words, fits the 40-45 second target at this pace.)

## Reference script library — one per theme

### Fear

**Quote:** "I cannot escape death, but I can escape the fear of it." — Epictetus, Discourses

> I cannot escape death, but I can escape the fear of it.
>
> Death was coming for me either way. I figured that out early. What wasn't guaranteed was spending every year before it scared half to death of something I couldn't stop anyway.
>
> Here's what I want you to do. When the fear shows up, ask if it's protecting you from something or just stealing today from you. Most of the time it's stealing. Let it go, and get back to living.
>
> What are you more afraid of — dying, or not really living first, because...

(96 words)

### Control

**Quote:** "You have power over your mind, not outside events. Realize this, and you will find strength." — Marcus Aurelius, Meditations, Book 6

> You have power over your mind, not outside events. Realize this, and you will find strength.
>
> Nobody ever handed me control over what happens to me. Weather, other people, bad luck — none of that answers to me. My own mind does, though. That's the one thing I've always owned outright.
>
> So stop spending your energy trying to control what was never yours to control. Put all of it into how you respond. That's the whole game. Every time.
>
> Follow me — I'll keep giving you what actually held up, because...

(97 words)

### Adversity

**Quote:** "The impediment to action advances action. What stands in the way becomes the way." — Marcus Aurelius, Meditations, Book 5.20

> The impediment to action advances action. What stands in the way becomes the way.
>
> Every setback I've had looked like the end of the plan. Most of them turned out to be the only way through, I just didn't see it yet.
>
> So next time something blocks you, don't just fight it. Look at what it's actually offering. There's usually a door in the wall, you just have to stop pushing long enough to find it.
>
> What's standing in your way right now that might actually be the way, because...

(96 words)
