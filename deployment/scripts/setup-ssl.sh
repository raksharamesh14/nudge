#!/bin/bash
# SSL Setup Script for Nudge Voice Bot
# Usage: ./setup-ssl.sh <domain> <email>

set -e

DOMAIN="${1:-your-domain.com}"
EMAIL="${2:-admin@$DOMAIN}"

if [ "$DOMAIN" = "your-domain.com" ]; then
    echo "❌ Please provide your domain name:"
    echo "Usage: ./setup-ssl.sh your-domain.com admin@your-domain.com"
    exit 1
fi

echo "🔒 Setting up SSL certificate for $DOMAIN..."

# Update Nginx configuration with actual domain
echo "📝 Updating Nginx configuration..."
sudo sed -i "s/your-domain.com/$DOMAIN/g" /etc/nginx/sites-available/nudge-bot

# Test Nginx configuration
echo "🧪 Testing Nginx configuration..."
sudo nginx -t

# Restart Nginx
echo "🔄 Restarting Nginx..."
sudo systemctl restart nginx

# Install certbot if not already installed
if ! command -v certbot &> /dev/null; then
    echo "📦 Installing certbot..."
    sudo apt-get update
    sudo apt-get install -y certbot python3-certbot-nginx
fi

# Obtain SSL certificate
echo "🎫 Obtaining SSL certificate from Let's Encrypt..."
sudo certbot --nginx \
    -d $DOMAIN \
    --non-interactive \
    --agree-tos \
    --email $EMAIL \
    --redirect

# Setup automatic renewal
echo "⏰ Setting up automatic certificate renewal..."
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# Test renewal
echo "🧪 Testing certificate renewal..."
sudo certbot renew --dry-run

echo ""
echo "✅ SSL setup completed successfully!"
echo ""
echo "🌐 Your bot is now available at: https://$DOMAIN"
echo "🔄 Certificate will auto-renew every 90 days"
echo ""
echo "📊 Check certificate status:"
echo "  sudo certbot certificates"
echo ""
echo "🔄 Manual renewal:"
echo "  sudo certbot renew"
echo ""