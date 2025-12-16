@echo off
echo 🚀 Ficore Mobile Backend Deployment Script
echo ==========================================

REM Ensure upload directories exist
echo 📁 Creating upload directories...
python ensure_upload_dirs.py
echo.

REM Check if git is initialized
if not exist ".git" (
    echo 📁 Initializing Git repository...
    git init
    git add .
    git commit -m "Initial Ficore Mobile Backend commit"
    echo ✅ Git repository initialized
) else (
    echo 📁 Git repository already exists
    echo 📝 Adding changes...
    git add .
    git commit -m "Update Ficore Mobile Backend - %date% %time%"
    echo ✅ Changes committed
)

echo.
echo 🌐 Next steps for deployment:
echo    1. Create GitHub repository: https://github.com/new
echo    2. Add remote: git remote add origin https://github.com/yourusername/ficore-mobile-backend.git
echo    3. Push code: git push -u origin main
echo    4. Deploy to Render: https://render.com
echo.
echo 📋 Environment Variables for Render:
echo    SECRET_KEY: [Auto-generate in Render]
echo    MONGO_URI: mongodb+srv://username:password@cluster.mongodb.net/ficore_mobile
echo    FLASK_ENV: production
echo.
echo 🧪 Test your API with:
echo    python test_api.py https://your-app-name.onrender.com
echo.
echo 📱 Update mobile app API URL to:
echo    https://your-app-name.onrender.com
echo.
echo 🎉 Your Ficore Mobile Backend is ready!
pause