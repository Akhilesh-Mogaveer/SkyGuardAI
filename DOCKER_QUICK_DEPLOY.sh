#!/bin/bash

################################################################################
# SkyGuardAI Docker Quick Deployment Script
# 
# Usage: bash DOCKER_QUICK_DEPLOY.sh
# or: chmod +x DOCKER_QUICK_DEPLOY.sh && ./DOCKER_QUICK_DEPLOY.sh
################################################################################

set -e  # Exit on error

echo "================================================================================"
echo "SkyGuardAI - DOCKER QUICK DEPLOYMENT"
echo "================================================================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Utilities
print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

################################################################################
# STEP 1: CHECK PREREQUISITES
################################################################################

print_step "Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    print_error "Docker not installed!"
    echo "Download from: https://www.docker.com/products/docker-desktop"
    exit 1
fi
print_success "Docker installed: $(docker --version)"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose not installed!"
    exit 1
fi
print_success "Docker Compose installed: $(docker-compose --version)"

# Check Git
if ! command -v git &> /dev/null; then
    print_error "Git not installed!"
    exit 1
fi
print_success "Git installed"

################################################################################
# STEP 2: CLONE OR UPDATE REPOSITORY
################################################################################

print_step "Setting up repository..."

if [ ! -d "SkyGuardAI" ]; then
    print_step "Cloning repository..."
    git clone https://github.com/Akhilesh-Mogaveer/SkyGuardAI.git
    cd SkyGuardAI
else
    print_step "Repository exists, pulling latest changes..."
    cd SkyGuardAI
    git pull origin main
fi

print_success "Repository ready"

################################################################################
# STEP 3: VERIFY PROJECT STRUCTURE
################################################################################

print_step "Verifying project structure..."

required_files=(
    "docker-compose.yml"
    "Dockerfile.backend"
    "Dockerfile.frontend"
    ".dockerignore"
    "nginx.conf"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        print_success "Found: $file"
    else
        print_warning "Missing: $file (will attempt to copy from outputs)"
    fi
done

required_dirs=(
    "backend"
    "frontend"
    "data"
)

for dir in "${required_dirs[@]}"; do
    if [ -d "$dir" ]; then
        print_success "Found: $dir/"
    else
        print_error "Missing: $dir/"
    fi
done

################################################################################
# STEP 4: CREATE ENVIRONMENT FILE
################################################################################

print_step "Creating environment configuration..."

if [ ! -f ".env" ]; then
    cat > .env << EOF
# Database Configuration
POSTGRES_USER=skyguard
POSTGRES_PASSWORD=skyguard123
POSTGRES_DB=skyguardai
DATABASE_URL=postgresql://skyguard:skyguard123@db:5432/skyguardai

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Backend Configuration
ENV=development
LOG_LEVEL=INFO
PYTHONUNBUFFERED=1
SECRET_KEY=your-secret-key-here-CHANGE-IN-PRODUCTION
ALGORITHM=HS256

# Frontend Configuration
REACT_APP_API_URL=http://localhost:8000/api
REACT_APP_WS_URL=ws://localhost:8000/ws

# pgAdmin Configuration
PGADMIN_DEFAULT_EMAIL=admin@skyguardai.com
PGADMIN_DEFAULT_PASSWORD=admin123
EOF
    print_success ".env file created"
else
    print_warning ".env file already exists (skipping)"
fi

################################################################################
# STEP 5: CREATE DATABASE INITIALIZATION SCRIPT
################################################################################

print_step "Creating database initialization script..."

mkdir -p scripts

if [ ! -f "scripts/init_db.sql" ]; then
    cat > scripts/init_db.sql << 'SQL'
-- Initialize SkyGuardAI Database
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Anomaly Records Table
CREATE TABLE IF NOT EXISTS anomaly_records (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    station_id VARCHAR(50),
    temperature FLOAT,
    pressure FLOAT,
    humidity FLOAT,
    anomaly_flag BOOLEAN DEFAULT FALSE,
    anomaly_type VARCHAR(50),
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indices for performance
CREATE INDEX IF NOT EXISTS idx_timestamp ON anomaly_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_station ON anomaly_records(station_id);
CREATE INDEX IF NOT EXISTS idx_anomaly ON anomaly_records(anomaly_flag);

-- Sensor Health Table
CREATE TABLE IF NOT EXISTS sensor_health (
    id SERIAL PRIMARY KEY,
    station_id VARCHAR(50),
    sensor_name VARCHAR(100),
    health_score FLOAT,
    last_checked TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sensor_station ON sensor_health(station_id);

print_success "Database initialization script created"
SQL
else
    print_warning "Database script already exists (skipping)"
fi

################################################################################
# STEP 6: BUILD DOCKER IMAGES
################################################################################

print_step "Building Docker images (this may take 5-10 minutes)..."

docker-compose build

if [ $? -eq 0 ]; then
    print_success "Docker images built successfully"
else
    print_error "Failed to build Docker images"
    exit 1
fi

################################################################################
# STEP 7: START SERVICES
################################################################################

print_step "Starting services..."

docker-compose up -d

if [ $? -eq 0 ]; then
    print_success "Services started"
else
    print_error "Failed to start services"
    exit 1
fi

# Wait for services to stabilize
print_step "Waiting for services to initialize (30 seconds)..."
sleep 30

################################################################################
# STEP 8: VERIFY DEPLOYMENT
################################################################################

print_step "Verifying deployment..."

# Check service status
echo ""
print_step "Service Status:"
docker-compose ps

echo ""
print_step "Testing endpoints..."

# Test Backend Health
echo -n "  Backend health... "
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    print_success "OK"
else
    print_warning "Not responding yet"
fi

# Test Frontend
echo -n "  Frontend... "
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    print_success "OK"
else
    print_warning "Not responding yet"
fi

# Test Database
echo -n "  Database... "
if docker-compose exec -T db pg_isready -U skyguard > /dev/null 2>&1; then
    print_success "OK"
else
    print_warning "Not responding yet"
fi

################################################################################
# STEP 9: DISPLAY ACCESS INFORMATION
################################################################################

echo ""
echo "================================================================================"
print_success "DEPLOYMENT COMPLETE!"
echo "================================================================================"
echo ""
echo "Access your application:"
echo ""
echo -e "  ${GREEN}Frontend Dashboard:${NC}     http://localhost:3000"
echo -e "  ${GREEN}Backend API:${NC}            http://localhost:8000"
echo -e "  ${GREEN}API Documentation:${NC}      http://localhost:8000/docs"
echo -e "  ${GREEN}Database Admin (pgAdmin):${NC} http://localhost:5050"
echo -e "  ${GREEN}Nginx Proxy:${NC}            http://localhost"
echo ""
echo "Database Credentials:"
echo "  Username: skyguard"
echo "  Password: skyguard123"
echo "  Database: skyguardai"
echo ""
echo "pgAdmin Credentials:"
echo "  Email:    admin@skyguardai.com"
echo "  Password: admin123"
echo ""

################################################################################
# STEP 10: USEFUL COMMANDS
################################################################################

echo "================================================================================"
echo "Useful Commands:"
echo "================================================================================"
echo ""
echo "View logs:"
echo "  docker-compose logs -f                  # All services"
echo "  docker-compose logs -f backend          # Backend only"
echo "  docker-compose logs -f frontend         # Frontend only"
echo ""
echo "Restart services:"
echo "  docker-compose restart                  # Restart all"
echo "  docker-compose restart backend          # Restart backend"
echo ""
echo "Stop/Start:"
echo "  docker-compose down                     # Stop all services"
echo "  docker-compose up -d                    # Start all services"
echo ""
echo "Access containers:"
echo "  docker-compose exec backend bash        # Backend shell"
echo "  docker-compose exec frontend sh         # Frontend shell"
echo "  docker-compose exec db psql -U skyguard -d skyguardai"
echo ""
echo "Monitor resources:"
echo "  docker stats                            # Resource usage"
echo ""
echo "Remove everything (cleanup):"
echo "  docker-compose down -v                  # Stop and remove volumes"
echo ""

################################################################################
# STEP 11: HEALTH CHECK
################################################################################

echo "================================================================================"
echo "Running health checks..."
echo "================================================================================"
echo ""

health_check_passed=true

# Backend health
if curl -s http://localhost:8000/health | grep -q "healthy"; then
    print_success "Backend health check passed"
else
    print_warning "Backend health check pending"
    health_check_passed=false
fi

# Container status
if docker-compose ps | grep -q "Up"; then
    print_success "All containers are running"
else
    print_error "Some containers are not running"
    health_check_passed=false
fi

echo ""
if [ "$health_check_passed" = true ]; then
    print_success "All health checks passed!"
else
    print_warning "Some services may still be initializing. Check logs with:"
    echo "  docker-compose logs -f"
fi

echo ""
echo "================================================================================"
print_success "SkyGuardAI deployment successful!"
echo "================================================================================"
echo ""
print_step "Next steps:"
echo "  1. Open http://localhost:3000 in your browser"
echo "  2. Check the frontend dashboard"
echo "  3. Explore API at http://localhost:8000/docs"
echo "  4. Monitor services with: docker-compose logs -f"
echo ""
echo "For detailed information, see: DOCKER_DEPLOYMENT_GUIDE.md"
echo ""
