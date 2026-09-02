Allen & Co | Five Questions to Start With in Glean

Use Glean to turn the EMS conference/attendee data into answers you'd otherwise have to dig for
across spreadsheets and reports. These five questions match what the connector actually indexes:
attendee registrations per conference, catering/activity assignments, and travel (air/ground)
logistics — all anchored to a specific conference (`EventInstanceID`, e.g. "SV26" = Sun Valley 2026).

1. "Who from [Company] is registered for [Conference]?"

Try asking:
"Who from [Company] is registered for [Conference]? List their attendee code/type and confirm
they're on the current conference roster. Cite the underlying records."

A strong response should give you:
The set of attendee-conference registration records for that company at that specific
`EventInstanceID`, not a mix of prior years' conferences.

Useful follow-ups:
"Are any of them marked inactive or deleted?"
"Which of these attendees also attended [prior conference]?"
"What company codes or attendee types are they registered under?"

This is the core Tier 2 use case — the registration/attendance record anchored to one conference
instance, which is exactly what avoids the "Jane Doe at Sun Valley 2025 vs. 2026" mix-up the
document model was built to fix.

2. "What are [Attendee]'s dietary or catering assignments for [Conference]?"

Try asking:
"Pull the catering table assignments for [Attendee name] at [Conference]. Include which activity
or meal each assignment is for, and flag any dietary or allergy notes on file."

A strong response should give you:
The Tier 3 catering records tied to that attendee and conference, including the activity name
(e.g. "Welcome Dinner") and any dietary/allergy information — the one PII field this model
deliberately keeps because catering can't function without it.

Useful follow-ups:
"What other activities is this attendee assigned to at this conference?"
"Are there other attendees from the same company with dietary notes for this event?"

This is a fast-follow use case once Tier 3 (catering/activity) data is indexed alongside Tier 2.

3. "What's [Attendee]'s travel schedule for [Conference]?"

Try asking:
"Give me the air and ground travel records for [Attendee] at [Conference] — flights with airline
and flight number, and any ground transportation, with dates. Cite the source records."

A strong response should give you:
A combined view of `travelAir` and `travelGround` records for that attendee at that conference,
since flight and ground transport live in separate views but should read as one itinerary.

Useful follow-ups:
"Which other attendees are arriving on the same day?"
"Does this attendee have any ground transport booked without a matching flight record?"

Useful for staff coordinating logistics day-of, where the answer today requires cross-referencing
two separate travel views by hand.

4. "Which activities is [Attendee] assigned to at [Conference], and when?"

Try asking:
"List [Attendee]'s activity assignments at [Conference] with their time ranges. Flag anything that
overlaps or is scheduled back-to-back."

A strong response should give you:
The `activityAttendee` records for that attendee/conference pair, with enough time detail to spot
scheduling conflicts — something that's hard to eyeball from a raw activity export.

Useful follow-ups:
"Who else is assigned to the same activity?"
"What does this attendee's full conference-day schedule look like once travel is factored in?"

Combines naturally with question 3 once both travel and activity records are indexed, to build a
full day-of picture for an attendee.

5. "How has [Company]'s attendance changed across conferences?"

Try asking:
"Compare [Company]'s registered attendees at [Conference A] versus [Conference B]. Who's new,
who's returning, and has their attendee code/type changed?"

A strong response should give you:
A comparison across two `EventInstanceID`s using the composite-keyed registration records, made
possible specifically because each attendee/conference pair is its own document rather than one
row per attendee that gets overwritten each year.

Useful follow-ups:
"Which companies have attended every conference in the last three years?"
"Are there companies that stopped attending after [year]?"

This depends on historical (non-current) `EventInstanceID`s being indexed and retained, not just
the current conference's hourly-refreshed data.

---

Note: two richer, name-bearing views (`v_Attendee_Global` for global identity, and
`v_Invitation_CurrentStatus` — the best source for "was `[Name]` at `[Conference]`?") are currently
disabled pending the client granting the read replica access to the `ConferenceImage` database.
Once enabled, questions like #1 and #5 will return attendee names directly instead of IDs/company
only — ask again after that access is granted to see the improvement.
