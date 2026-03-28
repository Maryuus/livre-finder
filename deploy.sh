#!/bin/bash
set -e

REPO_NAME="livre-finder"
DIR="/home/marius/projet/livres"

echo "=== LivreFinder Deploy ==="
echo "Utilisateur : $GH_USER"
echo "Repo : $REPO_NAME"
echo ""

cd "$DIR"

# Init git
if [ ! -d ".git" ]; then
  git init
  git branch -M main
fi

# Créer le repo GitHub via API
echo "Création du repo GitHub..."
RESPONSE=$(curl -s -w "\n%{http_code}" \
  -H "Authorization: token $GH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$REPO_NAME\",\"private\":false,\"description\":\"Find and open epub books on Apple Books\"}" \
  https://api.github.com/user/repos)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "201" ]; then
  echo "Repo cree avec succes !"
elif [ "$HTTP_CODE" = "422" ]; then
  echo "Repo existe deja, on continue..."
else
  echo "Erreur creation repo (HTTP $HTTP_CODE)"
  echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message',''))"
  exit 1
fi

# Stage + commit
git add .
git diff --cached --quiet || git commit -m "feat: LivreFinder - search epub across Gutenberg, UQAM and Open Library"

# Remote
git remote remove origin 2>/dev/null || true
git remote add origin "https://$GH_USER:$GH_TOKEN@github.com/$GH_USER/$REPO_NAME.git"

# Push
echo "Push vers GitHub..."
git push -u origin main

REPO_URL="https://github.com/$GH_USER/$REPO_NAME"
echo ""
echo "=== GitHub OK ==="
echo "Repo : $REPO_URL"
echo ""
echo "=== Etape suivante : Vercel ==="
echo "1. Va sur https://vercel.com/new"
echo "2. Clique 'Import Git Repository'"
echo "3. Selectionne : $REPO_NAME"
echo "4. Framework Preset : Other"
echo "5. Clique Deploy"
echo ""
echo "Ton app sera live en ~1 minute !"
