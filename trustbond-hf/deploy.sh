#!/bin/bash
# TrustBond Backend-Only Deployment to Hugging Face Spaces

echo "🚀 Deploying TrustBond Backend to Hugging Face Spaces..."
echo "📱 Frontend is already on Vercel"

# 1. Copy backend files only
echo "🔧 Copying backend files..."
rm -rf ../trustbond-hf/backend
mkdir -p ../trustbond-hf/backend/app
cp -r ../backend/app/* ../trustbond-hf/backend/app/

# 2. Copy essential backend files
echo "📋 Copying configuration files..."
cp ../backend/alembic.ini ../trustbond-hf/ 2>/dev/null || echo "No alembic.ini found"
cp ../backend/.env.example ../trustbond-hf/ 2>/dev/null || echo "No .env.example found"

# 3. Go to HF directory
cd ../trustbond-hf

# 6. Initialize git if not exists
if [ ! -d .git ]; then
    echo "📦 Initializing git repository..."
    git init
    git branch -M main
fi

# 7. Add all files
echo "📋 Adding files to git..."
git add .
git add -f frontend/build/static/*
git add -f frontend/build/index.html

# 8. Commit changes
echo "💾 Committing changes..."
git commit -m "Deploy TrustBond to Hugging Face Spaces
- FastAPI backend with ML capabilities
- React frontend build
- Evidence analysis with 15 advanced features
- Rwanda-specific safety platform"

# 9. Add remote and push
echo "🚀 Pushing to Hugging Face..."
# Replace with your actual HF repository URL
git remote add origin https://huggingface.co/spaces/your-username/trustbond 2>/dev/null || true
git push -u origin main --force

echo "✅ Deployment complete!"
echo "🌐 Your TrustBond app should be live at: https://huggingface.co/spaces/your-username/trustbond"
