# Deployment Directory

This directory contains all deployment-related files for the Nudge Voice Bot, organized for better maintainability.

## Directory Structure

```
deployment/
├── scripts/           # Deployment and management scripts
│   ├── deploy.sh      # Main deployment script
│   └── setup-ssl.sh   # SSL certificate setup
├── configs/           # Configuration files
│   ├── nginx.conf     # Nginx configuration template
│   └── ec2-config.yaml # EC2 instance configuration
└── docs/              # Documentation
    └── DEPLOYMENT.md  # Complete deployment guide
```

## Quick Start

### 1. Deploy to EC2

```bash
# From the project root
cd deployment/scripts
./deploy.sh your-domain.com
```

### 2. Setup SSL (Optional)

```bash
# After deployment
./setup-ssl.sh your-domain.com admin@your-domain.com
```

## Scripts Overview

### `deploy.sh` - Main Deployment Script

**Purpose**: Complete deployment of the voice bot to EC2

**Usage**:

```bash
./deploy.sh [domain]
```

**Features**:

- ✅ Docker containerization
- ✅ Nginx reverse proxy setup
- ✅ WebSocket support for Pipecat
- ✅ Automatic SSL (if domain provided)
- ✅ Log rotation and monitoring
- ✅ Health checks and restart policies

**Environment Variables Required**:

```bash
export DEEPGRAM_API_KEY="your_key"
export OPENAI_API_KEY="your_key"
export ANTHROPIC_API_KEY="your_key"
export CARTESIA_API_KEY="your_key"
export MONGODB_URI="your_uri"
export DAILY_API_KEY="your_key"
export TWILIO_ACCOUNT_SID="your_sid"
export TWILIO_AUTH_TOKEN="your_token"
```

### `setup-ssl.sh` - SSL Certificate Setup

**Purpose**: Automated SSL certificate setup using Let's Encrypt

**Usage**:

```bash
./setup-ssl.sh <domain> <email>
```

**Features**:

- ✅ Automatic Let's Encrypt certificate
- ✅ Nginx SSL configuration
- ✅ Auto-renewal setup
- ✅ HTTP to HTTPS redirect

## Configuration Files

### `nginx.conf` - Nginx Configuration Template

**Purpose**: Optimized Nginx configuration for voice bot

**Features**:

- ✅ WebSocket support for Pipecat
- ✅ Rate limiting for API endpoints
- ✅ Security headers
- ✅ Gzip compression
- ✅ Health check endpoint
- ✅ SSL configuration template

**Placeholders**:

- `your-domain.com` - Replace with your actual domain

### `ec2-config.yaml` - EC2 Instance Configuration

**Purpose**: EC2 instance specifications and security groups

**Features**:

- ✅ Optimized instance type (t3.small)
- ✅ Security group rules
- ✅ User data script
- ✅ Storage configuration
- ✅ Tags and metadata

## Deployment Workflow

### Initial Deployment

1. **Launch EC2 instance** using `ec2-config.yaml` specs
2. **Connect via SSH** to the instance
3. **Clone repository** and navigate to `deployment/scripts/`
4. **Set environment variables** for API keys
5. **Run deployment script**: `./deploy.sh your-domain.com`
6. **Setup SSL** (optional): `./setup-ssl.sh your-domain.com admin@your-domain.com`

### Updates

```bash
# Pull latest changes and redeploy
git pull origin main
./deploy.sh your-domain.com
```

### Monitoring

```bash
# Check container status
docker ps | grep nudge-bot

# View logs
docker logs -f nudge-bot

# Check resource usage
docker stats nudge-bot

# Monitor system resources
htop
df -h
```

## Cost Optimization

### Instance Sizing

- **t3.small**: $15/month - Perfect for 5-15 users
- **t3.medium**: $30/month - Good for 15-20+ users
- **t3.large**: $60/month - Overkill for your use case

### Total Monthly Cost

- **EC2 t3.small**: $15
- **EBS Storage**: $2
- **Data Transfer**: $5-10
- **Total**: ~$25-32/month

**vs ECS Fargate**: $63-107/month (2-4x more expensive!)

## Troubleshooting

### Common Issues

#### Container Won't Start

```bash
# Check logs
docker logs nudge-bot

# Check environment variables
docker exec nudge-bot env | grep -E "(API_KEY|URI)"

# Restart container
docker restart nudge-bot
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

# Consider upgrading to t3.medium
```

## Security Best Practices

### Instance Security

- ✅ Regular system updates
- ✅ Firewall configuration
- ✅ SSH key authentication only
- ✅ Security group restrictions

### Application Security

- ✅ Environment variables for secrets
- ✅ Non-root container user
- ✅ Minimal base images
- ✅ Regular security updates

## Backup Strategy

### Application Backup

```bash
# Code backup
git push origin main

# Environment backup
cp .env .env.backup

# Logs backup
tar -czf logs-backup-$(date +%Y%m%d).tar.gz logs/
```

### Instance Backup

- Create AMI snapshots
- Setup automated snapshots
- Test restore procedures

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

## Support

### Regular Tasks

- **Weekly**: Check logs and resource usage
- **Monthly**: Update dependencies and security patches
- **Quarterly**: Review costs and performance

### Emergency Procedures

- Container restart: `docker restart nudge-bot`
- Instance restart: AWS Console or `sudo reboot`
- Rollback: `git checkout previous-commit && ./deploy.sh`

---

## Quick Reference

| Command                                      | Purpose                   |
| -------------------------------------------- | ------------------------- |
| `./deploy.sh domain.com`                     | Deploy/update application |
| `./setup-ssl.sh domain.com email@domain.com` | Setup SSL certificate     |
| `docker logs nudge-bot`                      | View application logs     |
| `docker restart nudge-bot`                   | Restart application       |
| `sudo nginx -t`                              | Test Nginx config         |
| `sudo systemctl reload nginx`                | Reload Nginx              |
| `htop`                                       | Monitor system resources  |
| `df -h`                                      | Check disk space          |

For detailed deployment instructions, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
