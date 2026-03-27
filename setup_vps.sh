#!/bin/bash
# ================================================================
# SwarmAI VPS Setup Script
# Run on fresh Ubuntu VPS:  bash setup_vps.sh
# ================================================================

set -e

echo "=========================================="
echo "  SwarmAI Coordinator — VPS Setup"
echo "=========================================="

# 1. System deps
sudo apt-get update -q
sudo apt-get install -y python3 python3-pip git curl

# 2. Clone repo
cd ~
if [ -d "Ai-swarm" ]; then
    cd Ai-swarm && git pull
else
    git clone https://github.com/channupraveen/Ai-swarm.git
    cd Ai-swarm
fi

# 3. Install Python deps
pip3 install -r requirements.txt --quiet

# 4. Generate API key
SWARM_API_KEY="swarm-$(openssl rand -hex 16)"
echo "export SWARM_API_KEY=$SWARM_API_KEY" >> ~/.bashrc
source ~/.bashrc

echo ""
echo "  ⚠️  Your API Key: $SWARM_API_KEY"
echo "  Save this — all nodes must use this exact key!"
echo ""

# 5. Start coordinator in background
nohup env SWARM_API_KEY=$SWARM_API_KEY \
    uvicorn coordinator:app --host 0.0.0.0 --port 8200 \
    > coordinator.log 2>&1 &

sleep 3

# 6. Verify
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "UNKNOWN")

if curl -s http://localhost:8200/ | grep -q "SwarmAI"; then
    echo "=========================================="
    echo "  ✅ Coordinator is LIVE!"
    echo "=========================================="
    echo ""
    echo "  URL:     http://$PUBLIC_IP:8200"
    echo "  API Key: $SWARM_API_KEY"
    echo ""
    echo "  Now on EACH NODE machine run:"
    echo "  ┌──────────────────────────────────────────────────┐"
    echo "  │ export SWARM_COORDINATOR=http://$PUBLIC_IP:8200  │"
    echo "  │ export SWARM_API_KEY=$SWARM_API_KEY              │"
    echo "  │ export SWARM_PUBLIC_URL=http://NODE_IP:8100      │"
    echo "  │ python swarm.py start                            │"
    echo "  └──────────────────────────────────────────────────┘"
else
    echo "❌ Failed. Check coordinator.log"
    tail -20 coordinator.log
fi
