# Quick Start Guide - New Patient Features

## Launch the App
```bash
# From project root
python app.py

# Then open browser to http://localhost:5000
```

## Demo Login
- **Username:** `patient`
- **Password:** `patient123`

---

## 🎯 Try These Scenarios (In Order)

### Scenario 1: Browse Patients
1. Log in as `patient`
2. Click **People** in top navigation
3. See 4 demo patients:
   - ✓ Riya T. (Connected)
   - ✓ Mina R. (Connected)
   - 📝 Pema S. (Request received)
4. Search by name or filter by interest
5. Click on any patient to view full profile

### Scenario 2: View Patient Profile & Shared Communities
1. From browse page, click **Riya T.**
2. See:
   - Her bio, interests, and badges
   - **Shared communities:** grp-004, grp-005, grp-003
   - **Favorite movies:** Wild, Eat Pray Love, Secret Life of Walter Mitty
   - **Shared interests:** self-growth, motivation, women empowerment
3. Click **Send Message** button

### Scenario 3: Send Messages
1. From Riya's profile, click **Send Message**
2. You're taken to `/messages?user=riya-demo`
3. See conversation list with Riya showing:
   - Recent message preview
   - Timestamp
   - Unread badge (if new)
4. Click **Continue Conversation** to reply

### Scenario 4: Accept Connection Request
1. From browse page, click **Pema S.**
2. See connection status is **Request Received**
3. Click **Accept Connection** button
4. Now Pema appears in your Messages
5. You can message her

### Scenario 5: Join a Shared Community
1. While on any patient profile, scroll to "Shared Communities"
2. Click on a community card
3. Button to join the community
4. After joining, go to `/community` to see them listed

---

## 🔧 Key Files to Modify

### Add More Demo Patients
Edit `app.py` → `PATIENT_PROFILES` dictionary

```python
PATIENT_PROFILES: dict[str, dict[str, Any]] = {
    "your-username": {
        "username": "your-username",
        "display_name": "Your Name",
        "age": 30,
        "avatar": "🧑",
        "bio": "Quick bio here",
        "location": "City",
        "interests": ["healing", "self-growth"],
        "conditions": ["Condition 1"],
        "joined_communities": ["grp-001"],
        "movie_preferences": {
            "favorites": ["Movie 1", "Movie 2"],
            "watched_count": 5,
            "interested_in": ["healing", "inspiration"],
        },
        "connection_status": "Open to friendship",
        "badges": ["Helpful", "Active"],
        "member_since": "2026-03-01",
    },
}
```

### Pre-populate Messages
Edit `app.py` → `MESSAGES_DATA` list

```python
{
    "id": "msg-xxx",
    "from_user": "mina-demo",
    "to_user": "patient",
    "from_display": "Mina R.",
    "content": "Your message here",
    "timestamp": "2026-03-29 14:30",
    "read": False,
}
```

---

## 📱 API Test Examples

### Send Connection Request
```javascript
fetch('/api/send-connection-request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_username: 'mina-demo' })
})
.then(r => r.json())
.then(data => console.log(data));
```

### Accept Connection
```javascript
fetch('/api/accept-connection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_username: 'pema-demo' })
})
.then(r => r.json())
.then(data => console.log(data));
```

### Send Message
```javascript
fetch('/api/send-message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        to_username: 'mina-demo',
        content: 'Hi Mina! I loved your thoughts about creative healing.'
    })
})
.then(r => r.json())
.then(data => console.log(data));
```

### Join Community
```javascript
fetch('/api/join-community', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_id: 'grp-001' })
})
.then(r => r.json())
.then(data => console.log(data));
```

---

## 🧪 Test Cases Checklist

- [ ] Browse all patients without filter
- [ ] Search patients by name
- [ ] Filter patients by interest
- [ ] View full patient profile
- [ ] See shared communities on profile
- [ ] See shared movie interests
- [ ] Send connection request
- [ ] Accept pending connection
- [ ] View messages with connected patients
- [ ] Send new message to connected patient
- [ ] Join community from patient profile
- [ ] Get error when trying to message non-connected patient
- [ ] Cannot send message to self
- [ ] Connection status updates dynamically

---

## 🐛 Troubleshooting

### Messages not appearing?
- Check if users are connected (`USER_CONNECTIONS`)
- Verify message was saved to `MESSAGES_DATA`
- Check browser console for JavaScript errors

### Patient not showing up?
- Add to `PATIENT_PROFILES` dictionary
- Add to `USER_CONNECTIONS` for connection setup
- Clear browser cache (`Ctrl+Shift+Delete`)

### Routes not found?
- Verify `@app.route()` decorator is added
- Restart Flask server
- Check for typos in route name

### Templates not rendering?
- Check `render_template()` called with correct file name
- Verify template is in `/templates/` folder
- Check Jinja2 syntax ({% %}, {{ }})

---

## 📊 Data Flow

```
User Login
    ↓
Dashboard → Browse Patients (GET /patients)
    ↓
View Profile (GET /patient/<username>)
    ↓
Send Connection (POST /api/send-connection-request)
    ↓
View Messages (GET /messages)
    ↓
Send Message (POST /api/send-message)
    ↓
Message appears in conversation
```

---

## 🎨 Customization Ideas

### Change Avatar Emojis
Edit patient profiles in `PATIENT_PROFILES`:
```python
"avatar": "👨‍⚕️"  # Change emoji
```

### Add More Interests
Edit anywhere that filters by interest - add to select options in `patients_directory.html`

### Customize Colors
Edit CSS in template or `static/css/style.css` for:
- Connection status badges
- Message bubbles
- Community cards

### Add Timestamps to Messages
Modify message display format in `messages.html`:
```html
<span class="msg-time">{{ msg.timestamp }}</span>
```

---

## 🚦 Status

✅ **All features implemented and working**
✅ **Sample data loaded**
✅ **Routes tested**
✅ **Templates rendering**
✅ **Messages storing**
✅ **Connections tracking**

Ready to show on demo! 🎉
