# HomeHelper - UI Wireframes

## W1. Dashboard Overview (Main Page)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ HomeHelper Dashboard                                    🔄 Last Updated: 14:23│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─── System Status ───────────────────────────────────────────────────────┐ │
│ │ ✅ Redis Message Bus: Connected    📊 Memory: 85MB/8GB    💾 Disk: 15GB  │ │
│ │ 🔧 Active Apps: 4/5               ⚡ CPU: 12%           🌡️  Temp: 42°C   │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── App Status ──────────────────────────────────────────────────────────┐ │
│ │                                                                         │ │
│ │ ┌─ Camera Detection ─┐  ┌─ Telegram Bot ────┐  ┌─ Alarm Controller ──┐ │ │
│ │ │ ✅ RUNNING         │  │ ✅ RUNNING         │  │ ❌ STOPPED         │ │ │
│ │ │ Last Event: 14:20  │  │ Messages Sent: 3   │  │ Last Check: 13:45  │ │ │
│ │ │ Health: Good       │  │ Health: Good       │  │ Status: Disabled   │ │ │
│ │ │                    │  │                    │  │                    │ │ │
│ │ │ [View Logs] [Stop] │  │ [View Logs] [Stop] │  │ [Start] [View Logs]│ │ │
│ │ └────────────────────┘  └────────────────────┘  └────────────────────┘ │ │
│ │                                                                         │ │
│ │ ┌─ Weather Monitor ──┐  ┌─ Motion Detector ──┐                         │ │
│ │ │ 🟡 WARNING         │  │ ✅ RUNNING         │                        │ │
│ │ │ No data for 2h     │  │ Last Motion: 12:15  │                        │ │
│ │ │ Health: Degraded   │  │ Health: Good       │                        │ │
│ │ │                    │  │                    │                        │ │
│ │ │ [View Logs][Start] │  │ [View Logs] [Stop] │                        │ │
│ │ └────────────────────┘  └────────────────────┘                        │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── Recent Activity (logs)───────────────────────────────────────────────┐ │
│ │ 🕐 14:20 │ camera_detection  │ Person detected at front door            │ │
│ │ 🕐 14:20 │ telegram_bot     │ Message sent: "Motion at door"           │ │
│ │ 🕐 14:15 │ motion_detector  │ Motion detected in living room           │ │
│ │ 🕐 14:10 │ weather_monitor  │ Temperature updated: 22°C                │ │
│ │ 🕐 14:05 │ system          │ Health check completed on all apps       │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## W2. App Detail View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ← Back to Dashboard            Camera Detection Service                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─── App Information ─────────────────────────────────────────────────────┐ │
│ │ App ID:          camera_detection                                       │ │
│ │ Version:         v1.2.0                                                 │ │
│ │ Status:          ✅ RUNNING (PID: 1234)                                 │ │
│ │ Uptime:          2 hours 45 minutes                                     │ │
│ │ Health Check:    ✅ Healthy (last check: 14:22)                         │ │
│ │ Auto Start:      ✅ Enabled                                             │ │
│ │ Auto Restart:    ✅ Enabled                                             │ │
│ │                                                                         │ │
│ │                        [Start] [Stop] [Restart] [Enable/Disable]        │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── Resource Usage ──────────────────────────────────────────────────────┐ │
│ │ CPU Usage:    ████████░░ 8.2%                                           │ │
│ │ Memory:       ████████████████░░░░ 145MB / 512MB                        │ │
│ │ Threads:      3                                                         │ │
│ │ Last Updated: 14:23                                                     │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── Events Configuration ────────────────────────────────────────────────┐ │
│ │ PUBLISHES Events:                                                       │ │
│ │ • person_detected    - When person identified by camera                 │ │
│ │ • motion_detected    - When motion threshold exceeded                   │ │
│ │                                                                         │ │
│ │ SUBSCRIBES TO Events:                                                   │ │
│ │ • system_armed       - Enables detection sensitivity                    │ │
│ │ • system_disarmed    - Reduces detection sensitivity                    │ │
│ │ • house_mode_changed - Adjusts detection zones                          │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── Recent Events ───────────────────────────────────────────────────────┐ │
│ │ 🕐 14:20 │ PUBLISHED │ person_detected    │ confidence: 0.95,loc: front  │ │
│ │ 🕐 14:18 │ PUBLISHED │ motion_detected    │ zone: front_door             │ │
│ │ 🕐 14:15 │ RECEIVED  │ system_armed       │ Armed by user                │ │
│ │ 🕐 14:10 │ PUBLISHED │ person_detected    │ confidence: 0.87,loc: back   │ │
│ │ 🕐 14:05 │ RECEIVED  │ house_mode_changed │ Changed to: away_mode        │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│                                              [View Logs] [View Configuration]│
└─────────────────────────────────────────────────────────────────────────────┘
```

## W3. Log Viewer

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ← Back to App Detail               Camera Detection - Logs         [Refresh] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─── Log Filters ─────────────────────────────────────────────────────────┐ │
│ │ file: [latest ▼]                                                        │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── Log Entries ─────────────────────────────────────────────────────────┐ │
│ │ 2024-01-15 14:23:15 - INFO  - [camera_detection] - Person detected     │ │
│ │ 2024-01-15 14:23:15 - DEBUG - [camera_detection] - Confidence: 0.95    │ │
│ │ 2024-01-15 14:23:15 - INFO  - [camera_detection] - Publishing event    │ │
│ │ 2024-01-15 14:22:45 - INFO  - [camera_detection] - Health check OK     │ │
│ │ 2024-01-15 14:22:30 - DEBUG - [camera_detection] - Frame processed     │ │
│ │ 2024-01-15 14:22:15 - INFO  - [camera_detection] - Redis connected     │ │
│ │ 2024-01-15 14:22:00 - WARN  - [camera_detection] - High CPU usage      │ │
│ │ 2024-01-15 14:21:45 - INFO  - [camera_detection] - Detection started   │ │
│ │ 2024-01-15 14:21:30 - ERROR - [camera_detection] - Camera timeout      │ │
│ │ 2024-01-15 14:21:15 - INFO  - [camera_detection] - Connecting to cam   │ │
│ │                                                                         │ │
│ │                                                            Line 1-10/150│ │
│ │                                              [Previous] [Next] [Download]│ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## W4. System Status Detail

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ← Back to Dashboard                  System Status                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─── Hardware Status ─────────────────────────────────────────────────────┐ │
│ │                                                                         │ │
│ │ ┌─ CPU ──────────────────┐  ┌─ Memory ───────────────┐  ┌─ Storage ───┐ │ │
│ │ │ Usage:  ████░░░░░░ 12%  │  │ Used: ████████████░░ 85% │  │ 📁 Root    │ │ │
│ │ │ Temp:   🌡️  42°C        │  │ 6.8GB / 8.0GB           │  │ ████░░ 45% │ │ │
│ │ │ Load:   0.8, 0.6, 0.9   │  │ Available: 1.2GB         │  │ 15GB/32GB  │ │ │
│ │ │ Cores:  4               │  │                          │  │             │ │ │
│ │ └─────────────────────────┘  └──────────────────────────┘  └─────────────┘ │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── Redis Status ────────────────────────────────────────────────────────┐ │
│ │ Connection:      ✅ Connected                                            │ │
│ │ Memory Usage:    ████░░░░░░ 12MB                                         │ │
│ │ Peak Memory:     25MB                                                    │ │
│ │ Commands:        45,231 total                                            │ │
│ │ Clients:         5 connected                                             │ │
│ │ Uptime:          2 days 14 hours                                         │ │
│ │ Active Channels: homehelper:events:person_detected                       │ │
│ │                  homehelper:events:motion_detected                       │ │
│ │                  homehelper:events:system_armed                          │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ ┌─── Process Summary ─────────────────────────────────────────────────────┐ │
│ │ App Name          │ PID   │ CPU%  │ Memory │ Uptime    │ Status         │ │
│ │────────────────────────────────────────────────────────────────────────│ │
│ │ homehelper-main   │ 892   │ 2.1%  │  45MB  │ 2d 14h    │ ✅ Running     │ │
│ │ camera_detection  │ 1234  │ 8.2%  │ 145MB  │ 2h 45m    │ ✅ Running     │ │
│ │ telegram_bot      │ 1456  │ 0.8%  │  32MB  │ 2h 30m    │ ✅ Running     │ │
│ │ motion_detector   │ 1678  │ 3.5%  │  67MB  │ 1h 15m    │ ✅ Running     │ │
│ │ weather_monitor   │  -    │  -    │   -    │    -      │ 🟡 Warning     │ │
│ │ alarm_controller  │  -    │  -    │   -    │    -      │ ❌ Disabled    │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│                                                              [Restart Redis]│
└─────────────────────────────────────────────────────────────────────────────┘
```

## UI Component Specifications

### Status Indicators
- **✅ Green**: Running/Healthy
- **❌ Red**: Stopped/Error  
- **🟡 Yellow**: Warning/Degraded
- **⚪ Gray**: Unknown/Unavailable

### Color Scheme
- **Primary**: Bootstrap Blue (#0d6efd)
- **Success**: Green (#198754)
- **Warning**: Yellow (#ffc107) 
- **Danger**: Red (#dc3545)
- **Background**: Light Gray (#f8f9fa)

### Interactive Elements
- **Buttons**: Rounded corners, hover effects
- **Cards**: Subtle shadow, hover highlighting
- **Logs**: Monospace font, syntax highlighting for levels
- **Forms**: Clear validation, inline help text

### Responsive Behavior
- **Desktop**: 3-column app grid
- **Tablet**: 2-column app grid  
- **Mobile**: Single column stack, collapsible sections

### Manual Refresh Pattern
- **Dashboard**: Manual refresh button, shows last update time
- **Logs**: Refresh button with line count display
- **No auto-updates**: All data refresh is user-initiated