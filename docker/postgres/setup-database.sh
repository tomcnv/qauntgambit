#!/bin/bash
# DeepTrader Database Setup Script
# This script sets up the PostgreSQL database from scratch

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🗄️  DeepTrader Database Setup"
echo "=============================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if PostgreSQL container exists
if ! docker ps -a --format '{{.Names}}' | grep -q "^deeptrader-postgres$"; then
    echo "📦 PostgreSQL container not found. Starting with docker-compose..."
    cd "$ROOT_DIR"
    docker-compose up -d deeptrader-postgres deeptrader-redis
    echo "⏳ Waiting for PostgreSQL to be ready..."
    sleep 5
fi

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^deeptrader-postgres$"; then
    echo "🔄 Starting PostgreSQL container..."
    docker start deeptrader-postgres
    sleep 3
fi

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to accept connections..."
for i in {1..30}; do
    if docker exec deeptrader-postgres pg_isready -U deeptrader_user -d deeptrader > /dev/null 2>&1; then
        echo "✅ PostgreSQL is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ PostgreSQL failed to start after 30 seconds"
        exit 1
    fi
    sleep 1
done

echo ""
echo "Choose setup option:"
echo "  1) Apply migrations only (recommended for existing DB)"
echo "  2) Reset database and apply migrations (WARNING: deletes all data)"
echo "  3) Restore from schema.sql export"
echo ""
read -p "Enter option (1/2/3): " OPTION

case $OPTION in
    1)
        echo ""
        echo "📝 Applying migrations..."
        cd "$ROOT_DIR/deeptrader-backend/migrations"
        for f in *.sql; do
            echo "  → $f"
            docker exec -i deeptrader-postgres psql -U deeptrader_user -d deeptrader < "$f" 2>/dev/null || true
        done
        echo "✅ Migrations applied!"
        ;;
    2)
        echo ""
        echo "⚠️  WARNING: This will delete ALL data in the database!"
        read -p "Are you sure? (yes/no): " CONFIRM
        if [ "$CONFIRM" != "yes" ]; then
            echo "Cancelled."
            exit 0
        fi
        
        echo "🗑️  Dropping and recreating database..."
        docker exec -i deeptrader-postgres psql -U postgres << 'EOF'
DROP DATABASE IF EXISTS deeptrader;
CREATE DATABASE deeptrader OWNER deeptrader_user;
GRANT ALL PRIVILEGES ON DATABASE deeptrader TO deeptrader_user;
EOF
        
        echo "📝 Applying init.sql..."
        docker exec -i deeptrader-postgres psql -U deeptrader_user -d deeptrader < "$SCRIPT_DIR/init.sql"
        
        echo "📝 Applying migrations..."
        cd "$ROOT_DIR/deeptrader-backend/migrations"
        for f in *.sql; do
            echo "  → $f"
            docker exec -i deeptrader-postgres psql -U deeptrader_user -d deeptrader < "$f" 2>/dev/null || true
        done
        echo "✅ Database reset complete!"
        ;;
    3)
        echo ""
        echo "⚠️  WARNING: This will replace the current schema!"
        read -p "Are you sure? (yes/no): " CONFIRM
        if [ "$CONFIRM" != "yes" ]; then
            echo "Cancelled."
            exit 0
        fi
        
        echo "🗑️  Dropping and recreating database..."
        docker exec -i deeptrader-postgres psql -U postgres << 'EOF'
DROP DATABASE IF EXISTS deeptrader;
CREATE DATABASE deeptrader OWNER deeptrader_user;
GRANT ALL PRIVILEGES ON DATABASE deeptrader TO deeptrader_user;
EOF
        
        echo "📝 Restoring from schema.sql..."
        docker exec -i deeptrader-postgres psql -U deeptrader_user -d deeptrader < "$SCRIPT_DIR/schema.sql"
        echo "✅ Schema restored!"
        ;;
    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo ""
echo "📊 Database Statistics:"
docker exec deeptrader-postgres psql -U deeptrader_user -d deeptrader -c "
SELECT 
    schemaname,
    COUNT(*) as table_count
FROM pg_tables 
WHERE schemaname = 'public'
GROUP BY schemaname;
"

echo ""
read -p "Would you like to seed essential data (profiles, strategies, admin user)? (y/n): " SEED
if [ "$SEED" = "y" ] || [ "$SEED" = "Y" ]; then
    echo ""
    echo "🌱 Running seed scripts..."
    cd "$ROOT_DIR/deeptrader-backend"
    node scripts/seed-all.js
fi

echo ""
echo "✅ Database setup complete!"
echo ""
echo "Default admin credentials:"
echo "  Email:    ops@deeptrader.local"
echo "  Password: ControlTower!23"
