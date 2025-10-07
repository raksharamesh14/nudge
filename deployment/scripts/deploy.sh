#!/bin/bash
# Main deployment script for Nudge Voice Bot
# Usage: ./deploy.sh [domain]

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Configuration
APP_NAME="nudge-bot"
APP_DIR="/opt/nudge-bot"
SERVICE_USER="ec2-user"  # Changed for Amazon Linux
DOMAIN="${1:-your-domain.com}"  # Set this as first argument

echo "🚀 Deploying Nudge Voice Bot to EC2..."
echo "📁 Project root: $PROJECT_ROOT"
echo "🌐 Domain: $DOMAIN"

# Create application directory
sudo mkdir -p $APP_DIR
sudo chown $SERVICE_USER:$SERVICE_USER $APP_DIR
cd $APP_DIR

# Clone repository (replace with your repo)
if [ ! -d "$APP_DIR/.git" ]; then
    echo "📥 Cloning repository..."
    git clone https://github.com/your-username/nudge.git .
fi

# Pull latest changes
echo "🔄 Pulling latest changes..."
git pull origin main

# Create environment file
echo "⚙️ Setting up environment..."
cat > .env << EOF
# API Keys (set these as environment variables or use AWS Secrets Manager)
DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY:-your_deepgram_api_key}
OPENAI_API_KEY=${OPENAI_API_KEY:-your_openai_api_key}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-your_anthropic_api_key}
CARTESIA_API_KEY=${CARTESIA_API_KEY:-your_cartesia_api_key}
MONGODB_URI=${MONGODB_URI:-your_mongodb_uri}

# Daily (for production video/audio rooms)
DAILY_API_KEY=${DAILY_API_KEY:-your_daily_api_key}
DAILY_API_URL=https://api.daily.co/v1

# Twilio (for telephony)
TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID:-your_twilio_account_sid}
TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN:-your_twilio_auth_token}

# Application settings
USE_MONGODB=true
LOG_LEVEL=INFO
EOF

echo "📝 Created .env file. Please edit it with your actual API keys:"
echo "   nano .env"
echo "   # or"
echo "   vi .env"
echo ""
echo "Press Enter when you've updated the .env file with your API keys..."
read -p "Press Enter to continue..."

# Build Docker image
echo "🐳 Building Docker image..."
docker build -t $APP_NAME:latest .

# Stop existing container if running
echo "🛑 Stopping existing container..."
docker stop $APP_NAME 2>/dev/null || true
docker rm $APP_NAME 2>/dev/null || true

# Run new container
echo "▶️ Starting new container..."
docker run -d \
    --name $APP_NAME \
    --restart unless-stopped \
    --env-file .env \
    -p 8000:8000 \
    -v $APP_DIR/logs:/home/app/logs \
    $APP_NAME:latest

# Wait for container to be ready
echo "⏳ Waiting for application to start..."
sleep 10

# Check if container is running
if docker ps | grep -q $APP_NAME; then
    echo "✅ Container started successfully!"
else
    echo "❌ Container failed to start. Checking logs..."
    docker logs $APP_NAME
    exit 1
fi

# Setup Nginx configuration
echo "🌐 Configuring Nginx..."
# Use the config file from deployment/configs/ (Amazon Linux uses conf.d)
sudo cp $APP_DIR/deployment/configs/nginx.conf /etc/nginx/conf.d/$APP_NAME.conf
# Replace placeholder domain with actual domain
sudo sed -i "s/your-domain.com/$DOMAIN/g" /etc/nginx/conf.d/$APP_NAME.conf

# Test Nginx configuration
sudo nginx -t

# Start and enable Nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Setup SSL certificate (if domain is provided)
if [ "$DOMAIN" != "your-domain.com" ]; then
    echo "🔒 Setting up SSL certificate..."
    sudo yum install -y epel-release
    sudo yum install -y certbot python3-certbot-nginx
    sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN
fi

# Setup log rotation
echo "📝 Setting up log rotation..."
sudo tee /etc/logrotate.d/$APP_NAME > /dev/null << EOF
$APP_DIR/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 $SERVICE_USER $SERVICE_USER
    postrotate
        docker restart $APP_NAME > /dev/null 2>&1 || true
    endscript
}
EOF

# Setup monitoring script
echo "📊 Setting up monitoring..."
sudo tee /usr/local/bin/monitor-$APP_NAME.sh > /dev/null << 'EOF'
#!/bin/bash
# Simple monitoring script for the voice bot

APP_NAME="nudge-bot"
LOG_FILE="/var/log/nudge-bot-monitor.log"

# Check if container is running
if ! docker ps | grep -q $APP_NAME; then
    echo "$(date): Container $APP_NAME is not running. Attempting restart..." >> $LOG_FILE
    docker start $APP_NAME
fi

# Check memory usage
MEMORY_USAGE=$(docker stats --no-stream --format "table {{.MemPerc}}" $APP_NAME | tail -n 1 | sed 's/%//')
if (( $(echo "$MEMORY_USAGE > 80" | bc -l) )); then
    echo "$(date): High memory usage detected: ${MEMORY_USAGE}%" >> $LOG_FILE
fi

# Check disk space
DISK_USAGE=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "$(date): High disk usage detected: ${DISK_USAGE}%" >> $LOG_FILE
fi
EOF

sudo chmod +x /usr/local/bin/monitor-$APP_NAME.sh

# Setup cron job for monitoring
echo "⏰ Setting up monitoring cron job..."
(crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/monitor-$APP_NAME.sh") | crontab -

# Display status
echo ""
echo "🎉 Deployment completed successfully!"
echo ""
echo "📊 Status:"
docker ps | grep $APP_NAME
echo ""
echo "🌐 Application URL: http://$DOMAIN"
echo "📝 Logs: docker logs $APP_NAME"
echo "🔄 Restart: docker restart $APP_NAME"
echo ""
echo "📈 Monitoring:"
echo "  - Container status: docker ps | grep $APP_NAME"
echo "  - Resource usage: docker stats $APP_NAME"
echo "  - Application logs: docker logs -f $APP_NAME"
echo "  - System logs: tail -f /var/log/nudge-bot-monitor.log"
echo ""
echo "🔧 Management commands:"
echo "  - Stop: docker stop $APP_NAME"
echo "  - Start: docker start $APP_NAME"
echo "  - Restart: docker restart $APP_NAME"
echo "  - Update: $SCRIPT_DIR/deploy.sh $DOMAIN"
echo ""