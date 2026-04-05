# Fast Scalper - AWS Infrastructure

**Production-grade deployment using Terraform**

---

## 🌏 DEPLOYMENT REGIONS

### **Recommended: Singapore (ap-southeast-1)**

**Why Singapore?**
- Low-latency regional routing for Bybit workloads
- Strong AWS service coverage for ECS/RDS/ElastiCache
- Balanced cost/performance for a single-AZ launch

**Alternative Regions:**
- Hong Kong (ap-east-1)
- Tokyo (ap-northeast-1)
- US East (us-east-1)

---

## 🏗️ ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────┐
│                         VPC (10.0.0.0/16)                    │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │          Public Subnet (10.0.1.0/24)                 │   │
│  │                                                       │   │
│  │  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │ NAT Gateway  │  │ ALB (Health) │                │   │
│  │  └──────────────┘  └──────────────┘                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Private Subnet (10.0.2.0/24)                 │   │
│  │                                                       │   │
│  │  ┌────────────────────────────────────────┐         │   │
│  │  │  ECS Fargate / EC2                     │         │   │
│  │  │  ┌──────────────┐  ┌──────────────┐  │         │   │
│  │  │  │ Bot Instance │  │ Bot Instance │  │         │   │
│  │  │  │   (Primary)  │  │  (Standby)   │  │         │   │
│  │  │  └──────────────┘  └──────────────┘  │         │   │
│  │  └────────────────────────────────────────┘         │   │
│  │                                                       │   │
│  │  ┌──────────────┐  ┌──────────────┐                │   │
│  │  │ Redis Cluster│  │ TimescaleDB  │                │   │
│  │  │ (ElastiCache)│  │ (RDS/Aurora) │                │   │
│  │  └──────────────┘  └──────────────┘                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │      Monitoring & Logging                            │   │
│  │  - CloudWatch Metrics                                │   │
│  │  - CloudWatch Logs                                   │   │
│  │  - Prometheus + Grafana (optional)                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 COMPONENTS

### **Compute (Bot)**
- **Option A:** ECS Fargate (recommended)
  - Serverless, auto-scaling
  - 2-4 vCPU, 8-16 GB RAM
  - Cost: ~$100-200/month
  
- **Option B:** EC2 (for CPU pinning)
  - c6i.2xlarge or c7i.2xlarge
  - 8 vCPU, 16 GB RAM
  - Cost: ~$200-300/month

### **Redis (State & Coordination)**
- ElastiCache Redis 7.x
- cache.r6g.large (2 vCPU, 13 GB)
- Multi-AZ for HA
- Cost: ~$120/month

### **Database (Trade History)**
- RDS PostgreSQL with TimescaleDB
- db.r6g.large (2 vCPU, 16 GB)
- 100 GB storage
- Cost: ~$200/month

### **Networking**
- VPC with public/private subnets
- NAT Gateway for outbound
- Application Load Balancer (health checks)
- Cost: ~$50/month

### **Monitoring**
- CloudWatch (metrics, logs, alarms)
- Cost: ~$30/month

**Total Estimated Cost:** ~$500-800/month

---

## 🚀 QUICK START

### **Prerequisites**

```bash
# 1. Install Terraform
brew install terraform  # macOS
# or: https://www.terraform.io/downloads

# 2. Install AWS CLI
brew install awscli

# 3. Configure AWS credentials
aws configure
# Enter: Access Key, Secret Key, Region (ap-southeast-1), Output (json)

# 4. Verify access
aws sts get-caller-identity
```

### **Deploy Infrastructure**

```bash
cd infrastructure/terraform

# 1. Initialize Terraform
terraform init

# 2. Review plan
terraform plan

# 3. Deploy (takes 10-15 minutes)
terraform apply

# 4. Get outputs
terraform output
```

---

## 📁 DIRECTORY STRUCTURE

```
infrastructure/
├── README.md                    (this file)
├── terraform/
│   ├── main.tf                  (main configuration)
│   ├── variables.tf             (input variables)
│   ├── outputs.tf               (outputs)
│   ├── vpc.tf                   (VPC, subnets, NAT)
│   ├── ecs.tf                   (ECS cluster, service, task)
│   ├── redis.tf                 (ElastiCache Redis)
│   ├── rds.tf                   (RDS PostgreSQL/TimescaleDB)
│   ├── security-groups.tf       (security rules)
│   ├── iam.tf                   (IAM roles, policies)
│   ├── cloudwatch.tf            (monitoring, alarms)
│   └── alb.tf                   (load balancer for health)
├── docker/
│   ├── Dockerfile               (bot container)
│   └── docker-compose.yml       (local testing)
└── scripts/
    ├── deploy.sh                (deployment automation)
    ├── rollback.sh              (rollback script)
    └── monitor.sh               (monitoring script)
```

---

## 🔒 SECURITY

### **Network Security**
- Bot runs in private subnet (no direct internet access)
- NAT Gateway for outbound only
- Security groups whitelist OKX IPs only
- No SSH access (use AWS Systems Manager Session Manager)

### **Secrets Management**
- API keys stored in AWS Secrets Manager
- Automatic rotation supported
- Encryption at rest (KMS)
- Never hardcode credentials

### **Access Control**
- IAM roles with least privilege
- MFA required for production access
- CloudTrail audit logging
- VPC Flow Logs enabled

---

## 📊 MONITORING

### **CloudWatch Dashboards**
- Bot health status
- Decision loop latency
- Order placement rate
- Memory/CPU usage
- Network I/O

### **Alarms**
- Bot crash/restart
- High latency (>50ms)
- Memory usage >80%
- Failed health checks
- Circuit breaker trips

### **Logs**
- Centralized in CloudWatch Logs
- Searchable with CloudWatch Insights
- Retention: 30 days (configurable)
- Export to S3 for long-term storage

---

## 🔄 DEPLOYMENT STRATEGIES

### **Blue-Green Deployment**
```bash
# 1. Deploy new version (green)
terraform apply -var="deployment_color=green"

# 2. Test green environment
curl http://green-alb.example.com/health

# 3. Switch traffic to green
terraform apply -var="active_color=green"

# 4. Monitor for issues
# 5. Rollback if needed or destroy blue
```

### **Rolling Deployment**
- ECS manages rolling updates automatically
- Zero-downtime deployments
- Health checks prevent bad deployments

---

## 💰 COST OPTIMIZATION

### **Development Environment**
```
- EC2: t4g.small ($10/month)
- Redis: cache.t4g.micro ($15/month)
- RDS: db.t4g.micro ($20/month)
Total: ~$50/month
```

### **Production Environment**
```
- ECS Fargate: 2 tasks ($150/month)
- Redis: cache.r6g.large ($120/month)
- RDS: db.r6g.large ($200/month)
- Networking: NAT + ALB ($50/month)
- Monitoring: CloudWatch ($30/month)
Total: ~$550/month
```

### **Cost Savings**
- Use Savings Plans (30% discount)
- Reserved Instances for predictable workloads
- Spot Instances for non-critical tasks
- Auto-scaling to match demand

---

## 🧪 TESTING

### **Pre-Deployment Testing**
```bash
# 1. Build Docker image
cd infrastructure/docker
docker build -t fast-scalper:latest .

# 2. Test locally
docker-compose up

# 3. Run tests
docker exec -it fast-scalper python test_phase1.py
```

### **Post-Deployment Testing**
```bash
# 1. Check health
curl http://<alb-dns>/health

# 2. Check metrics
curl http://<alb-dns>/metrics

# 3. Monitor logs
aws logs tail /ecs/fast-scalper --follow
```

---

## 📚 NEXT STEPS

1. **Review Architecture** - Read this document
2. **Set up AWS** - Configure credentials
3. **Deploy to Dev** - Test in development environment
4. **Deploy to Prod** - Production deployment
5. **Monitor** - Set up dashboards and alarms
6. **Scale** - Adjust resources as needed

---

**Ready to deploy?** → Start with `terraform/README.md`


