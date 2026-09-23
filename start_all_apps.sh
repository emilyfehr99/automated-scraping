#!/bin/bash

# Master Script to Start All Three Analysis Apps
# This script starts all apps in parallel and monitors them

echo "🚀 Starting All Three Analysis Apps..."
echo "======================================"

# Function to start all apps
start_all_apps() {
    echo "🏒 Starting Stride Analysis App (Port 8237)..."
    cd stride_analysis_app
    ./start_24_7.sh start
    cd ..
    
    echo "🏋️ Starting Off-Ice Analysis App (Port 8238)..."
    cd off_ice_analysis_app
    ./start_24_7.sh start
    cd ..
    
    echo "🥅 Starting Goalie Analysis App (Port 8239)..."
    cd goalie_analysis_app
    ./start_24_7.sh start
    cd ..
    
    echo "📈 Starting Hudl Scraper & Dashboard App (Port 8240)..."
    cd hudl-scraping
    ./start_24_7.sh start
    cd ..
    
    echo ""
    echo "✅ All apps started successfully!"
    echo ""
    echo "🌐 Access your apps at:"
    echo "   Stride Analysis: http://localhost:8237"
    echo "   Off-Ice Analysis: http://localhost:8238"
    echo "   Goalie Analysis: http://localhost:8239"
    echo "   Hudl Scraper/Dashboard: http://localhost:8240"
    echo ""
}

# Function to stop all apps
stop_all_apps() {
    echo "🛑 Stopping all apps..."
    
    cd stride_analysis_app
    ./start_24_7.sh stop
    cd ..
    
    cd off_ice_analysis_app
    ./start_24_7.sh stop
    cd ..
    
    cd goalie_analysis_app
    ./start_24_7.sh stop
    cd ..
    
    cd hudl-scraping
    ./start_24_7.sh stop
    cd ..
    
    echo "✅ All apps stopped"
}

# Function to check status of all apps
check_status() {
    echo "📊 Checking status of all apps..."
    echo ""
    
    echo "🏒 Stride Analysis App:"
    cd stride_analysis_app
    ./start_24_7.sh status
    cd ..
    
    echo ""
    echo "🏋️ Off-Ice Analysis App:"
    cd off_ice_analysis_app
    ./start_24_7.sh status
    cd ..
    
    echo ""
    echo "🥅 Goalie Analysis App:"
    cd goalie_analysis_app
    ./start_24_7.sh status
    cd ..
    
    echo ""
    echo "📈 Hudl Scraper & Dashboard App:"
    cd hudl-scraping
    ./start_24_7.sh status
    cd ..
}

# Function to start monitoring for all apps
start_monitoring() {
    echo "👀 Starting monitoring for all apps..."
    echo "   This will auto-restart apps if they crash"
    echo ""
    
    # Start monitoring in background for each app
    cd stride_analysis_app
    ./start_24_7.sh monitor &
    STRIDE_MONITOR_PID=$!
    cd ..
    
    cd off_ice_analysis_app
    ./start_24_7.sh monitor &
    OFFICE_MONITOR_PID=$!
    cd ..
    
    cd goalie_analysis_app
    ./start_24_7.sh monitor &
    GOALIE_MONITOR_PID=$!
    cd ..
    
    cd hudl-scraping
    ./start_24_7.sh monitor &
    HUDL_MONITOR_PID=$!
    cd ..
    
    echo "✅ Monitoring started for all apps"
    echo "   Stride Monitor PID: $STRIDE_MONITOR_PID"
    echo "   Off-Ice Monitor PID: $OFFICE_MONITOR_PID"
    echo "   Goalie Monitor PID: $GOALIE_MONITOR_PID"
    echo "   Hudl Monitor PID: $HUDL_MONITOR_PID"
    echo ""
    echo "💡 To stop monitoring, use: pkill -f 'start_24_7.sh monitor'"
}

# Function to open all apps in Safari
open_in_safari() {
    echo "🌐 Opening all apps in Safari..."
    
    open -a Safari http://localhost:8237
    sleep 1
    open -a Safari http://localhost:8238
    sleep 1
    open -a Safari http://localhost:8239
    sleep 1
    open -a Safari http://localhost:8240
    
    echo "✅ All apps opened in Safari"
}

# Main script logic
case "$1" in
    start)
        start_all_apps
        ;;
    stop)
        stop_all_apps
        ;;
    status)
        check_status
        ;;
    monitor)
        start_monitoring
        ;;
    open)
        open_in_safari
        ;;
    *)
        echo "Usage: $0 {start|stop|status|monitor|open}"
        echo ""
        echo "Commands:"
        echo "  start   - Start all three analysis apps"
        echo "  stop    - Stop all three analysis apps"
        echo "  status  - Check status of all apps"
        echo "  monitor - Start monitoring (auto-restart on crash)"
        echo "  open    - Open all apps in Safari"
        echo ""
        echo "For 24/7 operation, run:"
        echo "  $0 start"
        echo "  $0 monitor"
        echo ""
        echo "To open in Safari:"
        echo "  $0 open"
        exit 1
        ;;
esac
