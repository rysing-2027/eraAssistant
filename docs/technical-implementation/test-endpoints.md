# Test Endpoints

This document describes the test endpoints available in ERA Assistant for debugging and development.

## Endpoints Overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check for monitoring |
| `/test/feishu` | GET | Test Feishu API connection |
| `/test/pipeline` | GET | Run full pipeline (fetch → process → store) |
| `/test/retry` | GET | Retry failed records |

---

## 1. Health Check

**Endpoint:** `GET /health`

**Description:** Simple health check endpoint for monitoring and load balancers.

**Response:**
```json
{
  "status": "healthy",
  "service": "ERA Assistant"
}
```

**Usage:**
```bash
curl http://localhost:8000/health
```

---

## 2. Test Feishu Connection

**Endpoint:** `GET /test/feishu`

**Description:** Tests connection to Feishu API and lists records with "Submitted" status.

**Response:**
```json
{
  "status": "success",
  "message": "Connected to Feishu! Found 2 records with 'Submitted' status",
  "record_count": 2,
  "sample_records": [
    {
      "record_id": "recOdqaZTz",
      "fields": {
        "name": [{"text": "rysing", "type": "text"}],
        "email": [{"link": "mailto:rysing@example.com", "text": "rysing@example.com", "type": "url"}],
        "status": "Submitted"
      }
    }
  ]
}
```

**Usage:**
```bash
curl http://localhost:8000/test/feishu
```

**When to use:**
- Verify Feishu credentials are correct
- Check if there are pending records to process
- Debug field names and structure

---

## 3. Test Full Pipeline

**Endpoint:** `GET /test/pipeline`

**Description:** Runs the complete processing pipeline:
1. Fetch records from Feishu with "Submitted" status
2. Download Excel attachments (parallel)
3. Parse Excel to extract `raw_text`
4. Store results in database

**Response:**
```json
{
  "status": "success",
  "new_records": 2,
  "success": 2,
  "failed": 0
}
```

**Usage:**
```bash
curl http://localhost:8000/test/pipeline
```

**Workflow:**
```
Feishu API → Download Files → Parse Excel → Database
    ↓              ↓               ↓            ↓
 Get records   Parallel (5)   df.to_string()  Store raw_text
```

**Status transitions:**
```
SUBMITTED → PROCESSING → READY_FOR_ANALYSIS
                     ↘ FAILED
```

**Notes:**
- Only processes records NOT already in database (by `feishu_record_id`)
- Uses `asyncio.Semaphore(5)` for parallel downloads (max 5 concurrent)
- Failed downloads are marked with error message in `error_message` field

---

## 4. Retry Failed Records

**Endpoint:** `GET /test/retry`

**Description:** Retries processing for records in FAILED status.

**Response:**
```json
{
  "status": "success",
  "retried": 2,
  "success": 2,
  "failed": 0
}
```

**Usage:**
```bash
curl http://localhost:8000/test/retry
```

**When to use:**
- After fixing Feishu permission issues
- After fixing network connectivity issues
- Manual retry after transient errors

**Behavior:**
- Finds all records with `status = FAILED`
- Re-downloads Excel files
- Re-parses and updates database
- Increments `retry_count` field

---

## Common Scenarios

### Scenario 1: First Time Setup

```bash
# 1. Check health
curl http://localhost:8000/health

# 2. Test Feishu connection
curl http://localhost:8000/test/feishu

# 3. Run pipeline
curl http://localhost:8000/test/pipeline
```

### Scenario 2: Permission Error Fixed

If you see `"failed": 2` with download errors after adding Feishu permissions:

```bash
# Retry the failed records
curl http://localhost:8000/test/retry
```

### Scenario 3: Check Database State

```bash
# Direct SQLite query
sqlite3 data/era.db "SELECT id, employee_name, status FROM records;"
```

---

## Error Handling

### 400 Bad Request on File Download

**Cause:** Missing Feishu API permissions

**Solution:**
1. Go to Feishu Open Platform (飞书开放平台)
2. Add permissions:
   - `bitable:record:read` - Read Bitable records
   - `drive:drive:readonly` - Download files
3. Retry: `curl http://localhost:8000/test/retry`

### No Records Found

**Cause:** All records already processed or no "Submitted" records in Feishu

**Solution:** Check Feishu Base for records with "Submitted" status

### Database Schema Mismatch

**Cause:** Old database schema after model changes

**Solution:**
```bash
rm data/era.db
# Restart server - will create fresh database
```

---

## Related Documents

- [Service Architecture](./service-architecture.md)
- [Excel Agent Flow](./excel-agent-flow.md)