#!/bin/bash

# Ficore Mobile Backend Deployment Script
echo "🚀 Ficore Mobile Backend Deployment Script"
echo "=========================================="

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "📁 Initializing Git repository..."
    git init
    git add .
    git commit -m "Initial Ficore Mobile Backend commit"
    echo "✅ Git repository initialized"
else
    echo "📁 Git repository already exists"
    echo "📝 Adding changes..."
    git add .
    git commit -m "Update Ficore Mobile Backend - $(date)"
    echo "✅ Changes committed"
fi

# Check if remote origin exists
if ! git remote get-url origin > /dev/null 2>&1; then
    echo ""
    echo "🔗 Git remote 'origin' not found"
    echo "📋 Please create a GitHub repository and run:"
    echo "   git remote add origin https://github.com/yourusername/ficore-mobile-backend.git"
    echo "   git branch -M main"
    echo "   git push -u origin main"
    echo ""
    echo "🌐 Then deploy to Render:"
    echo "   1. Go to https://render.com"
    echo "   2. Connect your GitHub repository"
    echo "   3. Set environment variables:"
    echo "      - SECRET_KEY: [Generate automatically]"
    echo "      - MONGO_URI: [Your MongoDB Atlas connection string]"
    echo "      - FLASK_ENV: production"
    echo ""
else
    echo "🔗 Pushing to GitHub..."
    git push origin main
    echo "✅ Code pushed to GitHub"
    echo ""
    echo "🌐 Next steps:"
    echo "   1. Go to https://render.com"
    echo "   2. Create new Web Service from your GitHub repo"
    echo "   3. Set environment variables in Render dashboard"
    echo "   4. Deploy and get your API URL"
fi

echo ""
echo "📋 Environment Variables needed for Render:"
echo "   SECRET_KEY: [Auto-generate in Render]"
echo "   MONGO_URI: mongodb+srv://username:password@cluster.mongodb.net/ficore_mobile"
echo "   FLASK_ENV: production"
echo ""
echo "🧪 Test your deployed API with:"
echo "   python test_api.py https://your-app-name.onrender.com"
echo ""
echo "📱 Update your mobile app's API base URL to:"
echo "   https://your-app-name.onrender.com"
echo ""
echo "🎉 Your Ficore Mobile Backend is ready for deployment!"