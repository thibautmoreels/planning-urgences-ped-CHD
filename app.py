import streamlit as st
import requests
import json
from datetime import datetime, timedelta
import calendar
import pandas as pd
from itertools import cycle
import os

# --- Configuration JSONBin.io ---
BIN_ID = os.getenv("BIN_ID", "6a847bb9da38895dfef3586c")  # ID par défaut (à remplacer si besoin)
API_KEY = os.getenv("JSONBIN_API_KEY", "")  # Clé API depuis secrets.toml
JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"

# --- Fonctions pour JSONBin.io ---
def lire_donnees():
    """Lit les données depuis JSONBin.io."""
    url = f"{JSONBIN_URL}/latest"
    headers = {"X-Master-Key": API_KEY} if API_KEY else {}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("record", {})
        else:
            st.error(f"Erreur de lecture JSONBin.io: {response.text}")
            return None
    except Exception as e:
        st.error(f"Erreur de connexion: {e}")
        return None

def ecrire_donnees(donnees):
    """Écrit les données dans JSONBin.io."""
    url = f"{JSONBIN_URL}"
    headers = {
        "X-Master-Key": API_KEY,
        "Content-Type": "application/json"
    }
    payload = {"record": donnees}
    try:
        response = requests.put(url, data=json.dumps(payload), headers=headers)
        return response.status_code == 200
    except Exception as e:
        st.error(f"Erreur d'écriture JSONBin.io: {e}")
        return False

# --- Fonctions utilitaires ---
def calculer_nb_gardes(tt, nb_total_nuits):
    """Calcule le nombre de gardes: round(nb_total_nuits * TT / 100)."""
    return round(nb_total_nuits * (tt / 100))

def generer_dates(date_debut, date_fin):
    """Génère toutes les dates entre deux dates."""
    dates = []
    date_actuelle = date_debut
    while date_actuelle <= date_fin:
        dates.append(date_actuelle)
        date_actuelle += timedelta(days=1)
    return dates

def generer_jours_gardes(dates):
    """Retourne les jours de garde (jeudi=3, vendredi=4, samedi=5, dimanche=6)."""
    return [date for date in dates if date.weekday() in [3, 4, 5, 6]]

def est_disponible(membre, date, planning_gardes, planning_journees, type_indispo="jour"):
    """
    Vérifie si un membre est disponible pour une date donnée.
    type_indispo peut être "jour" ou "nuit".
    """
    # Vérifie les indisponibilités manuelles
    date_str = date.strftime("%Y-%m-%d")
    if type_indispo == "jour" and date_str in membre["indisponibilites"].get("jour", []):
        return False
    if type_indispo == "nuit" and date_str in membre["indisponibilites"].get("nuit", []):
        return False

    # Vérifie si le membre a une garde la veille (pour les nuits)
    if type_indispo == "nuit":
        veille = date - timedelta(days=1)
        for garde in planning_gardes:
            if garde["Nom"] == membre["nom"] and garde["Date"] == veille:
                return False

    # Vérifie si le membre a déjà une garde ou une journée ce jour-là
    for garde in planning_gardes:
        if garde["Nom"] == membre["nom"] and garde["Date"] == date:
            return False
    for jour in planning_journees:
        if jour["Nom"] == membre["nom"] and jour["Date"] == date:
            return False

    return True

def repartir_gardes(equipe_gardes, dates):
    """Répartit les gardes pour les membres de l'équipe."""
    planning_gardes = []
    jours_gardes = generer_jours_gardes(dates)
    nb_total_nuits = len(jours_gardes)

    # Recalculer le nombre de gardes pour chaque membre
    for membre in equipe_gardes:
        membre["nb_gardes_restantes"] = calculer_nb_gardes(membre["TT"], nb_total_nuits)

    # Trier les membres par TT décroissant
    membres_tries = sorted(equipe_gardes, key=lambda x: x["TT"], reverse=True)

    for date in jours_gardes:
        for membre in cycle(membres_tries):  # Cycle pour équilibrer la répartition
            if membre["nb_gardes_restantes"] > 0 and est_disponible(membre, date, planning_gardes, [], "nuit"):
                planning_gardes.append({
                    "Date": date,
                    "Nom": membre["nom"],
                    "Jour": date.strftime("%A"),
                    "Type": "Garde (nuit)"
                })
                membre["nb_gardes_restantes"] -= 1
                break

    return planning_gardes

def repartir_journees(equipe_journees, dates, planning_gardes):
    """Répartit les journées de travail pour les membres de l'équipe."""
    planning_journees = []
    jours_travail = [date for date in dates if date.weekday() < 5]  # Lundi à Vendredi

    # Recalculer le nombre de journées pour chaque membre
    for membre in equipe_journees:
        nb_jours = (dates[-1] - dates[0]).days * membre["TT"] / 100 / 2  # Exemple temporaire
        membre["nb_journees_restantes"] = round(nb_jours)

    # Trier les membres par TT décroissant
    membres_tries = sorted(equipe_journees, key=lambda x: x["TT"], reverse=True)

    for date in jours_travail:
        for membre in cycle(membres_tries):
            if membre["nb_journees_restantes"] > 0 and est_disponible(membre, date, planning_gardes, planning_journees, "jour"):
                type_journee = "Urgences pédiatriques" if len(planning_journees) % 2 == 0 else "Renfort d'urgence"
                planning_journees.append({
                    "Date": date,
                    "Nom": membre["nom"],
                    "Type": type_journee
                })
                membre["nb_journees_restantes"] -= 1
                break

    return planning_journees

def generer_planning(donnees):
    """Génère le planning complet."""
    date_debut = datetime.strptime(donnees["metadata"]["date_debut"], "%Y-%m-%d")
    date_fin = datetime.strptime(donnees["metadata"]["date_fin"], "%Y-%m-%d")
    dates = generer_dates(date_debut, date_fin)

    planning_gardes = repartir_gardes(donnees["equipes"]["gardes"], dates)
    planning_journees = repartir_journees(donnees["equipes"]["journees"], dates, planning_gardes)

    # Mettre à jour les données avec le nouveau planning
    donnees["planning"] = {
        "gardes": [{"Date": garde["Date"].strftime("%Y-%m-%d"), "Nom": garde["Nom"], "Jour": garde["Jour"], "Type": garde["Type"]} for garde in planning_gardes],
        "journees": [{"Date": jour["Date"].strftime("%Y-%m-%d"), "Nom": jour["Nom"], "Type": jour["Type"]} for jour in planning_journees]
    }
    return donnees

def afficher_calendrier_mensuel(planning, titre):
    """Affiche le planning sous forme de calendrier mensuel."""
    if not planning or not planning.get("gardes") and not planning.get("journees"):
        st.warning("Aucun planning à afficher.")
        return

    # Extraire les mois uniques
    mois_uniques = set()
    for date_str in [g["Date"] for g in planning.get("gardes", [])] + [j["Date"] for j in planning.get("journees", [])]:
        mois_uniques.add(date_str[:7])  # AAAA-MM
    mois_uniques = sorted(mois_uniques)

    for mois in mois_uniques:
        st.subheader(f"### {mois}")
        annee, mois_num = int(mois[:4]), int(mois[5:7])
        last_day = calendar.monthrange(annee, mois_num)[1]
        dates_mois = pd.date_range(start=mois + "-01", end=mois + f"-{last_day}", freq='D')

        # Créer un DataFrame pour le mois
        jours_semaine = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        df_mois = pd.DataFrame(index=dates_mois, columns=jours_semaine)

        for date in dates_mois:
            jour_semaine = date.weekday()
            col_name = jours_semaine[jour_semaine]
            date_str = date.strftime("%Y-%m-%d")

            # Filtrer les plannings pour cette date
            gardes_date = [g for g in planning.get("gardes", []) if g["Date"] == date_str]
            journees_date = [j for j in planning.get("journees", []) if j["Date"] == date_str]

            # Afficher les gardes et journées
            textes = []
            for g in gardes_date:
                textes.append(f"{g['Nom']} (G)")
            for j in journees_date:
                textes.append(f"{j['Nom']} ({j['Type'][0]})")

            df_mois.loc[date, col_name] = "\n".join(textes) if textes else ""

        st.dataframe(df_mois)

# --- Interface Streamlit ---
def main():
    st.set_page_config(page_title="Planning Urgences", layout="wide")

    # Détecter si l'utilisateur est un admin ou un utilisateur standard
    query_params = st.experimental_get_query_params()
    is_admin = query_params.get("admin", [None])[0] == "true"
    user = query_params.get("user", [None])[0]

    # Charger les données depuis JSONBin.io
    donnees = lire_donnees()
    if not donnees:
        # Si pas de données, créer une structure par défaut
        donnees = {
            "metadata": {
                "periode": "2027-Q1",
                "date_debut": "2027-01-04",
                "date_fin": "2027-05-02",
                "priorite_journees": "Urgences pédiatriques",
                "date_creation": datetime.now().strftime("%Y-%m-%d")
            },
            "equipes": {
                "gardes": [
                    {"nom": "OB", "TT": 100, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "OP", "TT": 80, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "TM", "TT": 80, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "JCW", "TT": 70, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "MC", "TT": 60, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "LL", "TT": 50, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "JR", "TT": 50, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "LVB", "TT": 40, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "MR", "TT": 20, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "MP", "TT": 20, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "AJ", "TT": 20, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "ELR", "TT": 10, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "PK", "TT": 100, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "DJ", "TT": 100, "indisponibilites": {"jour": [], "nuit": []}}
                ],
                "journees": [
                    {"nom": "TM", "TT": 80, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "JCW", "TT": 70, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "MC", "TT": 60, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "JR", "TT": 50, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "LVB", "TT": 40, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "MR", "TT": 20, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "AJ", "TT": 20, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "ELR", "TT": 10, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "PK", "TT": 100, "indisponibilites": {"jour": [], "nuit": []}},
                    {"nom": "DJ", "TT": 100, "indisponibilites": {"jour": [], "nuit": []}}
                ]
            },
            "planning": {
                "gardes": [],
                "journees": []
            }
        }

    if is_admin:
        # --- Interface Admin ---
        st.title("👨‍⚕️ Interface Admin - Planning Urgences")

        # Onglets Admin
        tab_config, tab_planning, tab_export = st.tabs(["Configuration", "Planning", "Export"])

        with tab_config:
            st.header("⚙️ Configuration")

            # Métadonnées
            with st.expander("Métadonnées"):
                donnees["metadata"]["periode"] = st.text_input("Période", value=donnees["metadata"].get("periode", ""))
                donnees["metadata"]["date_debut"] = st.date_input("Date de début", value=datetime.strptime(donnees["metadata"]["date_debut"], "%Y-%m-%d")).strftime("%Y-%m-%d")
                donnees["metadata"]["date_fin"] = st.date_input("Date de fin", value=datetime.strptime(donnees["metadata"]["date_fin"], "%Y-%m-%d")).strftime("%Y-%m-%d")
                donnees["metadata"]["priorite_journees"] = st.selectbox("Priorité journées", ["Urgences pédiatriques", "Renfort d'urgence"], index=0 if donnees["metadata"]["priorite_journees"] == "Urgences pédiatriques" else 1)

            # Équipes
            with st.expander("Équipe pour les gardes"):
                for i, membre in enumerate(donnees["equipes"]["gardes"]):
                    col1, col2 = st.columns(2)
                    with col1:
                        membre["nom"] = st.text_input(f"Nom {i+1}", value=membre["nom"], key=f"garde_nom_{i}")
                        membre["TT"] = st.slider(f"TT {membre['nom']} (%)", 0, 100, value=membre["TT"], key=f"garde_tt_{i}")
                    with col2:
                        indispo_jour = st.date_input(
                            f"Indisponibilités (jour) pour {membre['nom']}",
                            value=[datetime.strptime(d, "%Y-%m-%d") for d in membre["indisponibilites"].get("jour", [])],
                            key=f"garde_jour_{i}"
                        )
                        indispo_nuit = st.date_input(
                            f"Indisponibilités (nuit) pour {membre['nom']}",
                            value=[datetime.strptime(d, "%Y-%m-%d") for d in membre["indisponibilites"].get("nuit", [])],
                            key=f"garde_nuit_{i}"
                        )
                        membre["indisponibilites"] = {
                            "jour": [d.strftime("%Y-%m-%d") for d in indispo_jour],
                            "nuit": [d.strftime("%Y-%m-%d") for d in indispo_nuit]
                        }

            with st.expander("Équipe pour les journées aux urgences"):
                for i, membre in enumerate(donnees["equipes"]["journees"]):
                    col1, col2 = st.columns(2)
                    with col1:
                        membre["nom"] = st.text_input(f"Nom {i+1}", value=membre["nom"], key=f"journee_nom_{i}")
                        membre["TT"] = st.slider(f"TT {membre['nom']} (%)", 0, 100, value=membre["TT"], key=f"journee_tt_{i}")
                    with col2:
                        indispo_jour = st.date_input(
                            f"Indisponibilités (jour) pour {membre['nom']}",
                            value=[datetime.strptime(d, "%Y-%m-%d") for d in membre["indisponibilites"].get("jour", [])],
                            key=f"journee_jour_{i}"
                        )
                        indispo_nuit = st.date_input(
                            f"Indisponibilités (nuit) pour {membre['nom']}",
                            value=[datetime.strptime(d, "%Y-%m-%d") for d in membre["indisponibilites"].get("nuit", [])],
                            key=f"journee_nuit_{i}"
                        )
                        membre["indisponibilites"] = {
                            "jour": [d.strftime("%Y-%m-%d") for d in indispo_jour],
                            "nuit": [d.strftime("%Y-%m-%d") for d in indispo_nuit]
                        }

            # Bouton pour sauvegarder les modifications
            if st.button("Sauvegarder la configuration"):
                if ecrire_donnees(donnees):
                    st.success("Configuration sauvegardée !")
                else:
                    st.error("Erreur de sauvegarde.")

        with tab_planning:
            st.header("📆 Génération du planning")
            if st.button("Générer le planning"):
                with st.spinner("Génération en cours..."):
                    donnees = generer_planning(donnees)
                    if ecrire_donnees(donnees):
                        st.success("Planning généré et sauvegardé !")
                    else:
                        st.error("Erreur lors de la sauvegarde.")

                # Afficher le planning
                st.subheader("Planning des gardes")
                afficher_calendrier_mensuel(donnees["planning"], "Planning des gardes")

                st.subheader("Planning des journées aux urgences")
                afficher_calendrier_mensuel(donnees["planning"], "Planning des journées")

        with tab_export:
            st.header("📥 Export du planning")
            # Option pour exporter en JSON
            if st.button("Exporter en JSON"):
                st.download_button(
                    label="Télécharger le JSON",
                    data=json.dumps(donnees, indent=4),
                    file_name=f"planning_{donnees['metadata']['periode']}.json",
                    mime="application/json"
                )

    else:
        # --- Interface Utilisateur ---
        if not user:
            st.error("Veuillez spécifier un utilisateur avec ?user=NOM dans l'URL.")
            return

        st.title(f"📅 Planning pour {user}")

        # Vérifier que l'utilisateur existe dans les équipes
        user_in_gardes = any(m["nom"] == user for m in donnees["equipes"]["gardes"])
        user_in_journees = any(m["nom"] == user for m in donnees["equipes"]["journees"])

        if not (user_in_gardes or user_in_journees):
            st.error(f"Utilisateur {user} non trouvé dans les équipes.")
            return

        # Afficher le planning global (lecture seule)
        st.header("Planning global (lecture seule)")
        st.subheader("Planning des gardes")
        afficher_calendrier_mensuel(donnees["planning"], "Planning des gardes")

        st.subheader("Planning des journées aux urgences")
        afficher_calendrier_mensuel(donnees["planning"], "Planning des journées")

        # Modifier ses indisponibilités
        st.header("📅 Vos indisponibilités")

        # Trouver le membre dans les équipes
        membre = None
        for m in donnees["equipes"]["gardes"]:
            if m["nom"] == user:
                membre = m
                break
        if not membre:
            for m in donnees["equipes"]["journees"]:
                if m["nom"] == user:
                    membre = m
                    break

        if membre:
            with st.expander(f"Modifier vos indisponibilités pour {user}"):
                col1, col2 = st.columns(2)
                with col1:
                    indispo_jour = st.date_input(
                        "Indisponibilités (jour)",
                        value=[datetime.strptime(d, "%Y-%m-%d") for d in membre["indisponibilites"].get("jour", [])],
                        key=f"user_jour_{user}"
                    )
                with col2:
                    indispo_nuit = st.date_input(
                        "Indisponibilités (nuit)",
                        value=[datetime.strptime(d, "%Y-%m-%d") for d in membre["indisponibilites"].get("nuit", [])],
                        key=f"user_nuit_{user}"
                    )

                if st.button("Sauvegarder mes indisponibilités"):
                    membre["indisponibilites"] = {
                        "jour": [d.strftime("%Y-%m-%d") for d in indispo_jour],
                        "nuit": [d.strftime("%Y-%m-%d") for d in indispo_nuit]
                    }
                    if ecrire_donnees(donnees):
                        st.success("Indisponibilités sauvegardées !")
                    else:
                        st.error("Erreur de sauvegarde.")

if __name__ == "__main__":
    main()
