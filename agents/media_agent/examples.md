# Example proposed plans (documentation only)

These examples show the **shape** of output a future planner might produce. They are not executed from this folder.

---

## Example A — Add a movie (search then add)

**User:** "Add the movie *Arrival* to my library if it's not there."

**Proposed plan (illustrative):**

1. **Step 1 — `radarr_search` (v1)**  
   - Args: `{ "title": "Arrival" }`  
   - Intent: Confirm match and whether the title is already monitored.

2. **Step 2 — `radarr_add` (v1)** *(conditional)*  
   - Args: `{ "title": "Arrival" }`  
   - Intent: Only if step 1 shows it is safe and desired; gateway may still refuse.

---

## Example B — Check download queue

**User:** "What's downloading right now?"

**Proposed plan:**

1. **Step 1 — `sabnzbd_queue` (v1)**  
   - Args: `{}`  
   - Intent: Read-only inspection of the queue.

---

## Example C — Series add with explicit consent for writes

**User:** "Search for *Severance* and add the 2022 show if you find it."

**Proposed plan:**

1. **Step 1 — `sonarr_search` (v1)**  
   - Args: `{ "title": "Severance" }`  
   - Intent: Disambiguate series.

2. **Step 2 — `sonarr_add` (v1)**  
   - Args: `{ "title": "Severance" }`  
   - Intent: User explicitly requested add after search; gateway enforces policy.
