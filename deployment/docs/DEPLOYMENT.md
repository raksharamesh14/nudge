# EC2 Deployment Guide for Nudge Voice Bot

## Overview

This guide will help you deploy your Nudge Voice Bot on AWS EC2, optimized for <20 concurrent users with external API dependencies.

## Prerequisites

- AWS account with EC2 access
- Domain name (optional, for SSL)
- Environment variables for API keys

## Step 1: Launch EC2 Instance

### Instance Configuration

```bash
# Recommended instance type for your use case
Instance Type: t3.small (2 vCPU, 2 GB RAM)
AMI: Ubuntu 22.04 LTS
Storage: 20 GB GP3 (encrypted)
Security Group: Custom (see below)
```

### Security Group Rules

```
SSH (22): Your IP only
HTTP (80): 0.0.0.0/0
HTTPS (443): 0.0.0.0/0
Custom TCP (8000): 127.0.0.1/32 (internal only)
```

## Step 2: Connect to Instance

```bash
# Connect via SSH
ssh -i your-key.pem ubuntu@your-instance-ip

# Update system
sudo apt update && sudo apt upgrade -y
```

## Step 3: Deploy Application

```bash
# Clone your repository
git clone https://github.com/your-username/nudge.git
cd nudge

# Set environment variables
export DEEPGRAM_API_KEY="your_deepgram_key"
export OPENAI_API_KEY="your_openai_key"
export ANTHROPIC_API_KEY="your_anthropic_key"
export CARTESIA_API_KEY="your_cartesia_key"
export MONGODB_URI="your_mongodb_uri"
export DAILY_API_KEY="your_daily_key"
export TWILIO_ACCOUNT_SID="your_twilio_sid"
export TWILIO_AUTH_TOKEN="your_twilio_token"
export DOMAIN="your-domain.com"  # Optional

# Run deployment script
chmod +x deploy.sh
./deploy.sh
```

## Step 4: Setup SSL (Optional)

```bash
# If you have a domain name
chmod +x setup-ssl.sh
./setup-ssl.sh your-domain.com admin@your-domain.com
```

## Step 5: Verify Deployment

```bash
# Check container status
docker ps | grep nudge-bot

# Check application logs
docker logs nudge-bot

# Test health endpoint
curl http://localhost:8000/health

# Test through Nginx
curl http://your-domain.com/health
```

## Management Commands

### Container Management

```bash
# View logs
docker logs -f nudge-bot

# Restart application
docker restart nudge-bot

# Update application
git pull origin main
./deploy.sh

# Stop application
docker stop nudge-bot
```

### Monitoring

```bash
# Check resource usage
docker stats nudge-bot

# Check system resources
htop
df -h
free -h

# View monitoring logs
tail -f /var/log/nudge-bot-monitor.log
```

### Nginx Management

```bash
# Test configuration
sudo nginx -t

# Reload configuration
sudo systemctl reload nginx

# View access logs
sudo tail -f /var/log/nginx/nudge-bot-access.log

# View error logs
sudo tail -f /var/log/nginx/nudge-bot-error.log
```

## Cost Optimization

### Instance Sizing

- **t3.small**: $15/month - Perfect for 5-15 users
- **t3.medium**: $30/month - Good for 15-20+ users
- **t3.large**: $60/month - Overkill for your use case

### Reserved Instances

```bash
# Save 30-60% with Reserved Instances
# 1-year term: ~30% savings
# 3-year term: ~60% savings
```

### Monitoring Costs

```bash
# Check AWS Cost Explorer
# Set up billing alerts
# Monitor data transfer costs
```

## Troubleshooting

### Common Issues

#### Container Won't Start

```bash
# Check logs
docker logs nudge-bot

# Check environment variables
docker exec nudge-bot env | grep -E "(API_KEY|URI)"

# Restart with verbose logging
docker run --rm -it --env-file .env nudge-bot:latest
```

#### WebSocket Connection Issues

```bash
# Check Nginx configuration
sudo nginx -t

# Verify WebSocket headers
curl -H "Upgrade: websocket" -H "Connection: Upgrade" http://your-domain.com/

# Check firewall rules
sudo ufw status
```

#### High Memory Usage

```bash
# Check memory usage
docker stats nudge-bot

# Restart container
docker restart nudge-bot

# Consider upgrading to t3.medium
```

### Performance Tuning

#### Optimize for Voice

```bash
# Increase WebSocket timeouts in Nginx
# Adjust VAD parameters in pipeline.py
# Monitor API response times
```

#### Database Optimization

```bash
# Use MongoDB Atlas (already external)
# Monitor connection pool size
# Check query performance
```

## Security Best Practices

### Instance Security

```bash
# Regular updates
sudo apt update && sudo apt upgrade -y

# Firewall configuration
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'

# SSH key authentication only
# Disable password authentication
```

### Application Security

```bash
# Environment variables
# Never commit API keys to git
# Use AWS Secrets Manager for production

# Container security
# Run as non-root user
# Use minimal base images
# Regular security updates
```

## Backup Strategy

### Application Backup

```bash
# Backup application code
git push origin main

# Backup environment configuration
cp .env .env.backup

# Backup logs
tar -czf logs-backup-$(date +%Y%m%d).tar.gz logs/
```

### Instance Backup

```bash
# Create AMI snapshot
# Setup automated snapshots
# Test restore procedures
```

## Scaling Considerations

### When to Scale Up

- Memory usage > 80%
- CPU usage > 70%
- Response times > 2 seconds
- Concurrent users > 15

### Scaling Options

1. **Vertical Scaling**: Upgrade to t3.medium/large
2. **Horizontal Scaling**: Multiple instances + load balancer
3. **Migration to ECS**: When you need auto-scaling

## Support and Maintenance

### Regular Tasks

- Weekly: Check logs and resource usage
- Monthly: Update dependencies and security patches
- Quarterly: Review costs and performance

### Emergency Procedures

- Container restart: `docker restart nudge-bot`
- Instance restart: AWS Console or `sudo reboot`
- Rollback: `git checkout previous-commit && ./deploy.sh`

---

## Quick Reference

| Command                       | Purpose                   |
| ----------------------------- | ------------------------- |
| `./deploy.sh`                 | Deploy/update application |
| `docker logs nudge-bot`       | View application logs     |
| `docker restart nudge-bot`    | Restart application       |
| `sudo nginx -t`               | Test Nginx config         |
| `sudo systemctl reload nginx` | Reload Nginx              |
| `htop`                        | Monitor system resources  |
| `df -h`                       | Check disk space          |

## Cost Summary

- **EC2 t3.small**: $15/month
- **EBS Storage**: $2/month
- **Data Transfer**: $5-10/month
- **Total**: ~$25-32/month

**vs ECS Fargate**: $63-107/month (2-4x more expensive!)
