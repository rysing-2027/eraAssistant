# Project Overview - ERA Assistant

## What is ERA Assistant?

ERA (Employee Report Analysis) Assistant is an AI-powered system that automatically analyzes employee product experience reports and provides personalized feedback.

## Why We Built This

- **Before**: Managers manually reviewed 50+ reports/week, taking 30+ minutes each
- **After**: AI analyzes in under 2 minutes, provides consistent scoring, instant feedback

## Who Uses This System

| Role | What They Do | Main Touchpoint |
|------|--------------|-----------------|
| **Employees** | Submit product experience reports | Feishu Base (多维表) |
| **Admin** | Monitor system, configure AI models | Web Dashboard |
| **AI System** | Analyze reports, calculate scores | Runs automatically |

## How It Works (Simple Flow)

```
Employee submits report in Feishu
           ↓
System detects new submission (every 5 min)
           ↓
AI extracts and reads the Excel file
           ↓
3 AI models analyze independently (triple validation)
           ↓
Average score calculated
           ↓
Employee receives email with feedback
           ↓
Done! (Status updated in dashboard)
```

## Key Features

1. **Automatic Detection** - No manual triggering needed
2. **Triple Validation** - 3 AI models ensure fair, consistent scoring
3. **Real-time Dashboard** - See all reports and their status
4. **Flexible Configuration** - Change AI models and prompts anytime
5. **Email Notifications** - Employees get feedback within minutes

## Success Metrics

- Analysis time: < 10 minutes per report
- Consistency: 3 AI models agree within 10% variance
- Coverage: 100% of submitted reports processed
- Satisfaction: Employees receive feedback same day