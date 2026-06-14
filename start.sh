#!/bin/bash

# Aller dans le répertoire du script
cd "$(dirname "$0")"

# Vérifier si le venv existe, sinon le créer
if [ ! -d "venv" ]; then
    echo "📦 Environnement virtuel non trouvé. Création en cours..."
    python3 -m venv venv
fi

# Activer l'environnement virtuel
source venv/bin/activate

# Installer les dépendances si besoin (optionnel)
if [ ! -f "venv/.installed" ]; then
    echo "📚 Installation des dépendances depuis requirements.txt..."
    pip install --upgrade pip
    pip install streamlit pandas plotly
    # Ajoutez ici les autres librairies nécessaires
    touch venv/.installed
fi

# Lancer le tableau de bord Streamlit
echo "🚀 Lancement de l'application..."
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0