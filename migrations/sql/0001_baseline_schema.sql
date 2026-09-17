--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: btree_gist; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;


--
-- Name: EXTENSION btree_gist; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION btree_gist IS 'support for indexing common datatypes in GiST';


--
-- Name: kuma_log_audit(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.kuma_log_audit() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
        DECLARE
            v_id_ligne TEXT;
            v_avant JSONB;
            v_apres JSONB;
            v_modifies JSONB;
            v_auteur_app TEXT;
        BEGIN
            -- Identifiant de la ligne auditée
            -- On suppose une colonne 'id' sur les tables auditées
            -- (convention Kuma Data Core : voir 01-naming.md).
            IF TG_OP = 'DELETE' THEN
                v_id_ligne := OLD.id::TEXT;
            ELSE
                v_id_ligne := NEW.id::TEXT;
            END IF;

            -- Construction des JSONB selon l'opération
            IF TG_OP = 'INSERT' THEN
                v_avant := NULL;
                v_apres := to_jsonb(NEW);
                v_modifies := NULL;

            ELSIF TG_OP = 'UPDATE' THEN
                v_avant := to_jsonb(OLD);
                v_apres := to_jsonb(NEW);

                -- Calcul des champs réellement modifiés
                SELECT jsonb_object_agg(
                    key,
                    jsonb_build_array(v_avant -> key, v_apres -> key)
                )
                INTO v_modifies
                FROM jsonb_object_keys(v_apres) AS key
                WHERE v_avant -> key IS DISTINCT FROM v_apres -> key;

                -- Si aucun champ n'a changé (UPDATE sans modification effective),
                -- on ne crée pas d'entrée d'audit
                IF v_modifies IS NULL OR v_modifies = '{}'::JSONB THEN
                    RETURN NULL;
                END IF;

            ELSIF TG_OP = 'DELETE' THEN
                v_avant := to_jsonb(OLD);
                v_apres := NULL;
                v_modifies := NULL;
            END IF;

            -- Identifiant applicatif (peut être absent)
            BEGIN
                v_auteur_app := current_setting('kuma.auteur_applicatif', true);
                IF v_auteur_app = '' THEN
                    v_auteur_app := NULL;
                END IF;
            EXCEPTION WHEN OTHERS THEN
                v_auteur_app := NULL;
            END;

            -- Insertion dans audit_log
            INSERT INTO audit_log (
                table_auditee,
                schema_audite,
                type_operation,
                id_ligne_auditee,
                champs_modifies,
                valeurs_avant,
                valeurs_apres,
                utilisateur_pg,
                auteur_applicatif,
                adresse_client
            ) VALUES (
                TG_TABLE_NAME,
                TG_TABLE_SCHEMA,
                LEFT(TG_OP, 1),
                v_id_ligne,
                v_modifies,
                v_avant,
                v_apres,
                current_user,
                v_auteur_app,
                inet_client_addr()
            );

            RETURN NULL;  -- AFTER trigger : valeur de retour ignorée
        END;
        $$;


--
-- Name: FUNCTION kuma_log_audit(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.kuma_log_audit() IS 'Fonction generique d''audit Kuma Data Core. A utiliser en AFTER trigger sur les tables structurantes. Suppose une colonne id (PK) sur la table auditee.';


--
-- Name: valider_hierarchie_localites(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.valider_hierarchie_localites() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
        DECLARE
            v_type_parent TEXT;
        BEGIN
            -- Continent : racine, jamais de parent (renforce ck_localites_continent_racine).
            IF NEW.type_localite = 'continent' THEN
                IF NEW.parent_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'Hierarchie localites : un continent ne peut avoir de parent (code=%, parent_id=%)',
                        NEW.code, NEW.parent_id;
                END IF;
                RETURN NEW;
            END IF;

            -- Tout type non-continent doit avoir un parent.
            IF NEW.parent_id IS NULL THEN
                RAISE EXCEPTION
                    'Hierarchie localites : le type % exige un parent (code=%)',
                    NEW.type_localite, NEW.code;
            END IF;

            SELECT type_localite INTO v_type_parent FROM localites WHERE id = NEW.parent_id;
            IF v_type_parent IS NULL THEN
                RAISE EXCEPTION
                    'Hierarchie localites : parent_id=% introuvable (code=%)',
                    NEW.parent_id, NEW.code;
            END IF;

            -- Matrice parent-enfant (Conakry : commune directement sous region_administrative).
            IF NOT (
                (NEW.type_localite = 'region_supranationale' AND v_type_parent = 'continent')
                OR (NEW.type_localite = 'pays'
                    AND v_type_parent IN ('continent', 'region_supranationale'))
                OR (NEW.type_localite = 'region_administrative' AND v_type_parent = 'pays')
                OR (NEW.type_localite = 'prefecture' AND v_type_parent = 'region_administrative')
                OR (NEW.type_localite = 'commune'
                    AND v_type_parent IN ('prefecture', 'region_administrative'))
                OR (NEW.type_localite = 'site'
                    AND v_type_parent IN ('commune', 'prefecture', 'region_administrative'))
            ) THEN
                RAISE EXCEPTION
                    'Hierarchie localites invalide : un % ne peut avoir un parent de type % '
                    '(code=%, parent_id=%)',
                    NEW.type_localite, v_type_parent, NEW.code, NEW.parent_id;
            END IF;

            RETURN NEW;
        END;
        $$;


--
-- Name: FUNCTION valider_hierarchie_localites(); Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON FUNCTION public.valider_hierarchie_localites() IS 'Valide la matrice parent-enfant de localites (BEFORE INSERT OR UPDATE). Cloture datee de la dette du trigger 007 (annonce des migration 003, jamais bati). Portee minimale : matrice + continent-racine ; pas de detection de cycles.';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    table_auditee text NOT NULL,
    schema_audite text DEFAULT 'public'::text NOT NULL,
    type_operation character(1) NOT NULL,
    id_ligne_auditee text NOT NULL,
    champs_modifies jsonb,
    valeurs_avant jsonb,
    valeurs_apres jsonb,
    utilisateur_pg text NOT NULL,
    auteur_applicatif text,
    adresse_client inet,
    horodatage timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT ck_audit_log_type_operation CHECK ((type_operation = ANY (ARRAY['I'::bpchar, 'U'::bpchar, 'D'::bpchar])))
);


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.audit_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: calage_couverture; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.calage_couverture (
    id bigint NOT NULL,
    referentiel_code character varying(120) NOT NULL,
    localite_id bigint NOT NULL,
    justification text NOT NULL,
    version character varying(20) DEFAULT 'v1'::character varying NOT NULL,
    actif boolean DEFAULT true NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE calage_couverture; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.calage_couverture IS 'Domaine de couverture des referentiels de calage : localites qualifiees pour le transport, avec justification. Pilote la couverture geographique des consommateurs (ADR-0004, couverture progressive).';


--
-- Name: calage_couverture_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.calage_couverture ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.calage_couverture_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: contributeurs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contributeurs (
    id bigint NOT NULL,
    code character varying(100) NOT NULL,
    nom_complet text NOT NULL,
    nom_court text,
    email_principal text NOT NULL,
    type_contributeur character varying(50) NOT NULL,
    statut character varying(50) NOT NULL,
    biographie text,
    affiliation_principale text,
    pays_iso3 character varying(3),
    url_publique text,
    orcid character varying(19),
    domaines_expertise text[],
    date_premier_engagement date,
    date_dernier_engagement date,
    notes_internes text,
    actif boolean DEFAULT true NOT NULL,
    desactive_le timestamp with time zone,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_contributeurs_actif_desactive_coherent CHECK ((((actif = true) AND (desactive_le IS NULL)) OR ((actif = false) AND (desactive_le IS NOT NULL)))),
    CONSTRAINT ck_contributeurs_orcid_format CHECK (((orcid IS NULL) OR ((orcid)::text ~ '^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9X]{4}$'::text))),
    CONSTRAINT ck_contributeurs_pays_iso3_format CHECK (((pays_iso3 IS NULL) OR ((pays_iso3)::text ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT ck_contributeurs_statut_valide CHECK (((statut)::text = ANY ((ARRAY['actif'::character varying, 'inactif'::character varying, 'archive'::character varying, 'suspendu'::character varying])::text[]))),
    CONSTRAINT ck_contributeurs_type_valide CHECK (((type_contributeur)::text = ANY ((ARRAY['editeur_principal'::character varying, 'contributeur_regulier'::character varying, 'contributeur_invite'::character varying, 'expert_externe'::character varying, 'institution'::character varying, 'agent_automatique'::character varying])::text[])))
);


--
-- Name: contributeurs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.contributeurs ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.contributeurs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: grandeurs_metier; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grandeurs_metier (
    id bigint NOT NULL,
    grandeur_code character varying(80) NOT NULL,
    localite_id bigint NOT NULL,
    series_metadonnees_id bigint NOT NULL,
    periode_type character varying(8) NOT NULL,
    annee_debut integer NOT NULL,
    annee_fin integer NOT NULL,
    mois integer,
    version_formule integer NOT NULL,
    valeur double precision,
    valide_du timestamp with time zone DEFAULT now() NOT NULL,
    valide_au timestamp with time zone,
    statut character varying(16) DEFAULT 'brut'::character varying NOT NULL,
    niveau_confiance_derive character varying(1) NOT NULL,
    niveau_confiance_override character varying(1),
    commentaire_editorial text,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_grandeurs_metier_annees_coherentes CHECK ((annee_fin >= annee_debut)),
    CONSTRAINT ck_grandeurs_metier_niveau_confiance_derive_valide CHECK (((niveau_confiance_derive)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[]))),
    CONSTRAINT ck_grandeurs_metier_niveau_confiance_override_valide CHECK (((niveau_confiance_override IS NULL) OR ((niveau_confiance_override)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[])))),
    CONSTRAINT ck_grandeurs_metier_periode_coherente CHECK (((((periode_type)::text = 'annuel'::text) AND (mois IS NULL)) OR (((periode_type)::text = 'mensuel'::text) AND (mois IS NOT NULL) AND ((mois >= 1) AND (mois <= 12))) OR (((periode_type)::text = 'statique'::text) AND (mois IS NULL)))),
    CONSTRAINT ck_grandeurs_metier_periode_type_valide CHECK (((periode_type)::text = ANY ((ARRAY['mensuel'::character varying, 'annuel'::character varying, 'statique'::character varying])::text[]))),
    CONSTRAINT ck_grandeurs_metier_periode_validite_coherente CHECK (((valide_au IS NULL) OR (valide_au > valide_du))),
    CONSTRAINT ck_grandeurs_metier_statut_valide CHECK (((statut)::text = ANY ((ARRAY['brut'::character varying, 'valide_auto'::character varying, 'valide_humain'::character varying, 'publie'::character varying, 'deprecie'::character varying])::text[]))),
    CONSTRAINT ck_grandeurs_metier_version_formule_positive CHECK ((version_formule >= 1))
);


--
-- Name: TABLE grandeurs_metier; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.grandeurs_metier IS 'Grandeurs metier calculees par Kuma a partir des mesures brutes. Premiere table de fabrication editoriale phase 1 (etape 1-5). F1 stockee, agregations annuelles et mensuelles. Versioning temporel par (valide_du, valide_au) + EXCLUDE BTree-GiST sur identite metier etendue avec version_formule. Statut editorial et niveau de confiance derive/override par couche service editoriale.';


--
-- Name: COLUMN grandeurs_metier.periode_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_metier.periode_type IS 'Granularite temporelle de l''agregation : annuel (1 ligne par (localite, grandeur, annee, version_formule), mois NULL) ou mensuel (12 lignes par annee, mois 1-12). Cf. cadrage phase 1 Q2 et Q6.';


--
-- Name: COLUMN grandeurs_metier.version_formule; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_metier.version_formule IS 'Version de la formule de calcul en vigueur au moment de l''insertion. Lien implicite avec grandeurs_referentiel.version_formule_actuelle pour la grandeur concernee. Incremente lors de toute revision methodologique. Inclus dans l''EXCLUDE pour permettre la coexistence v1/v2 apres upgrade (spec 1-5 sec. 3.2, cadrage Q7).';


--
-- Name: COLUMN grandeurs_metier.statut; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_metier.statut IS 'Statut editorial Kuma : brut (calcule non valide), valide_auto (controle qualite automatique passe), valide_humain (validation editoriale humaine), publie (publie publiquement), deprecie (retire du circuit editorial). Transitions encadrees par la couche service Python (cf. kuma_data_core.editorial.statuts).';


--
-- Name: COLUMN grandeurs_metier.niveau_confiance_derive; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_metier.niveau_confiance_derive IS 'Niveau de confiance derive automatiquement par la couche service a partir des regles R1-R4 (cf. spec mecaniques-transverses-phase-1 sec. 6.4). A = haute, B = moyenne, C = basse. Recalcule a chaque modification de methode_collecte ou source_id de la serie.';


--
-- Name: COLUMN grandeurs_metier.niveau_confiance_override; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_metier.niveau_confiance_override IS 'Override editorial du niveau derive. NULL = pas override (valeur effective = derive). Sinon valeur effective = override. Pose par la fonction service overrider_niveau_confiance avec justification obligatoire dans commentaire_editorial.';


--
-- Name: grandeurs_metier_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.grandeurs_metier ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.grandeurs_metier_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: grandeurs_referentiel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.grandeurs_referentiel (
    id bigint NOT NULL,
    code character varying(80) NOT NULL,
    libelle text NOT NULL,
    unite_id bigint NOT NULL,
    famille character varying(2) NOT NULL,
    strategie_calcul character varying(16) NOT NULL,
    methode_calcul_doc text,
    version_formule_actuelle integer DEFAULT 1 NOT NULL,
    description text,
    actif boolean DEFAULT true NOT NULL,
    desactive_le timestamp with time zone,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_grandeurs_referentiel_actif_desactive_coherent CHECK ((((actif = true) AND (desactive_le IS NULL)) OR ((actif = false) AND (desactive_le IS NOT NULL)))),
    CONSTRAINT ck_grandeurs_referentiel_famille_valide CHECK (((famille)::text = ANY ((ARRAY['F1'::character varying, 'F2'::character varying])::text[]))),
    CONSTRAINT ck_grandeurs_referentiel_strategie_calcul_valide CHECK (((strategie_calcul)::text = ANY ((ARRAY['stockee'::character varying, 'calculee_volee'::character varying])::text[]))),
    CONSTRAINT ck_grandeurs_referentiel_version_formule_positive CHECK ((version_formule_actuelle >= 1))
);


--
-- Name: TABLE grandeurs_referentiel; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.grandeurs_referentiel IS 'Referentiel des grandeurs Kuma. 15 grandeurs traduites (1-1C) + 5 grandeurs brutes ingerees (1-2b) = 20 entrees post-1-2b. Le lieu de stockage physique d''une F1 stockee est determine par series_metadonnees.methode_collecte (cadrage Q7 v1.3).';


--
-- Name: COLUMN grandeurs_referentiel.code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_referentiel.code IS 'Cle naturelle metier (ASCII pur, snake_case, citee par les FK aval). Cf. 01-naming.md section Codes metier des referentiels.';


--
-- Name: COLUMN grandeurs_referentiel.libelle; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_referentiel.libelle IS 'Titre humain de la grandeur (accents et casse normale autorises).';


--
-- Name: COLUMN grandeurs_referentiel.famille; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_referentiel.famille IS 'F1 : grandeur ontologique (mesuree ou derivee simple). F2 : grandeur parametree (calcul necessitant des parametres utilisateur).';


--
-- Name: COLUMN grandeurs_referentiel.strategie_calcul; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_referentiel.strategie_calcul IS 'stockee : valeur persistee dans grandeurs_metier. calculee_volee : recalculee a chaque consultation, dependante du perimetre.';


--
-- Name: COLUMN grandeurs_referentiel.version_formule_actuelle; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.grandeurs_referentiel.version_formule_actuelle IS 'Compteur applicatif de la formule en vigueur. Incremente a chaque revision methodologique. Initial : 1.';


--
-- Name: grandeurs_referentiel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.grandeurs_referentiel ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.grandeurs_referentiel_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: localites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.localites (
    id bigint NOT NULL,
    code character varying(100) NOT NULL,
    nom text NOT NULL,
    type_localite character varying(50) NOT NULL,
    parent_id bigint,
    pays_iso3 character varying(3),
    latitude numeric(11,8),
    longitude numeric(12,8),
    altitude_metres integer,
    population_estimee integer,
    annee_population integer,
    fuseau_horaire character varying(50),
    notes text,
    actif boolean DEFAULT true NOT NULL,
    desactive_le timestamp with time zone,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    code_administratif_national character varying(8),
    CONSTRAINT ck_localites_actif_desactive_le CHECK ((((actif = true) AND (desactive_le IS NULL)) OR ((actif = false) AND (desactive_le IS NOT NULL)))),
    CONSTRAINT ck_localites_annee_population_bornes CHECK (((annee_population IS NULL) OR ((annee_population >= 1900) AND (annee_population <= 2100)))),
    CONSTRAINT ck_localites_code_administratif_format CHECK (((code_administratif_national IS NULL) OR ((code_administratif_national)::text ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT ck_localites_code_format CHECK (((code)::text ~ '^[a-z][a-z0-9_]*$'::text)),
    CONSTRAINT ck_localites_continent_racine CHECK (((((type_localite)::text = 'continent'::text) AND (parent_id IS NULL)) OR ((type_localite)::text <> 'continent'::text))),
    CONSTRAINT ck_localites_demographie_coherente CHECK ((((population_estimee IS NULL) AND (annee_population IS NULL)) OR ((population_estimee IS NOT NULL) AND (annee_population IS NOT NULL)))),
    CONSTRAINT ck_localites_latitude_bornes CHECK (((latitude IS NULL) OR ((latitude >= ('-90'::integer)::numeric) AND (latitude <= (90)::numeric)))),
    CONSTRAINT ck_localites_longitude_bornes CHECK (((longitude IS NULL) OR ((longitude >= ('-180'::integer)::numeric) AND (longitude <= (180)::numeric)))),
    CONSTRAINT ck_localites_pays_iso3_format CHECK (((pays_iso3 IS NULL) OR ((pays_iso3)::text ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT ck_localites_population_positive CHECK (((population_estimee IS NULL) OR (population_estimee >= 0))),
    CONSTRAINT ck_localites_type_valide CHECK (((type_localite)::text = ANY ((ARRAY['continent'::character varying, 'region_supranationale'::character varying, 'pays'::character varying, 'region_administrative'::character varying, 'prefecture'::character varying, 'commune'::character varying, 'site'::character varying])::text[])))
);


--
-- Name: COLUMN localites.type_localite; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.localites.type_localite IS '7 valeurs : continent, region_supranationale, pays, region_administrative, prefecture, commune, site. prefecture ajoutee en densification prefectorale Etape 1 (niveau pays > region > prefecture > commune).';


--
-- Name: COLUMN localites.code_administratif_national; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.localites.code_administratif_national IS 'Code administratif officiel externe (decret guineen de codification 2025, 3 lettres majuscules, ex. CKY). Nullable. Convention identifiant externe comme sources.doi / sources.isbn. Candidat cle de jointure INS / gouvernemental.';


--
-- Name: localites_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.localites ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.localites_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: mesures_ressource; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mesures_ressource (
    id bigint NOT NULL,
    serie_id bigint NOT NULL,
    instant_mesure date NOT NULL,
    valeur double precision NOT NULL,
    valide_du timestamp with time zone DEFAULT now() NOT NULL,
    valide_au timestamp with time zone,
    statut character varying(16) DEFAULT 'brut'::character varying NOT NULL,
    niveau_confiance_derive character varying(1) NOT NULL,
    niveau_confiance_override character varying(1),
    commentaire_editorial text,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_mesures_ressource_niveau_confiance_derive_valide CHECK (((niveau_confiance_derive)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[]))),
    CONSTRAINT ck_mesures_ressource_niveau_confiance_override_valide CHECK (((niveau_confiance_override IS NULL) OR ((niveau_confiance_override)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[])))),
    CONSTRAINT ck_mesures_ressource_periode_coherente CHECK (((valide_au IS NULL) OR (valide_au > valide_du))),
    CONSTRAINT ck_mesures_ressource_statut_valide CHECK (((statut)::text = ANY ((ARRAY['brut'::character varying, 'valide_auto'::character varying, 'valide_humain'::character varying, 'publie'::character varying, 'deprecie'::character varying])::text[])))
);


--
-- Name: TABLE mesures_ressource; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.mesures_ressource IS 'Mesures journalieres ingerees depuis sources externes. Premiere table metier operationnelle phase 1. Versioning temporel par (valide_du, valide_au) + EXCLUDE BTree-GiST sur identite metier (serie_id, instant_mesure). Statut editorial et niveau de confiance derive/override par couche service editoriale.';


--
-- Name: COLUMN mesures_ressource.statut; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.mesures_ressource.statut IS 'Statut editorial Kuma : brut (importe non valide), valide_auto (controle qualite automatique passe), valide_humain (validation editoriale humaine), publie (publie publiquement), deprecie (retire du circuit editorial). Transitions encadrees par la couche service Python (cf. kuma_data_core.editorial.statuts).';


--
-- Name: COLUMN mesures_ressource.niveau_confiance_derive; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.mesures_ressource.niveau_confiance_derive IS 'Niveau de confiance derive automatiquement par la couche service a partir des regles R1-R4 (cf. spec mecaniques-transverses-phase-1 sec. 6.4). A = haute, B = moyenne, C = basse. Recalcule a chaque modification de methode_collecte ou source_id de la serie.';


--
-- Name: COLUMN mesures_ressource.niveau_confiance_override; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.mesures_ressource.niveau_confiance_override IS 'Override editorial du niveau derive. NULL = pas override (valeur effective = derive). Sinon valeur effective = override. Pose par la fonction service overrider_niveau_confiance avec justification obligatoire dans commentaire_editorial.';


--
-- Name: mesures_ressource_horaires; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mesures_ressource_horaires (
    id bigint NOT NULL,
    serie_id bigint NOT NULL,
    instant_mesure timestamp with time zone NOT NULL,
    valeur double precision NOT NULL,
    valide_du timestamp with time zone DEFAULT now() NOT NULL,
    valide_au timestamp with time zone,
    statut character varying(16) DEFAULT 'brut'::character varying NOT NULL,
    niveau_confiance_derive character varying(1) NOT NULL,
    niveau_confiance_override character varying(1),
    commentaire_editorial text,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_mesures_ressource_horaires_niveau_confiance_derive_valide CHECK (((niveau_confiance_derive)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[]))),
    CONSTRAINT ck_mesures_ressource_horaires_niveau_confiance_override_valide CHECK (((niveau_confiance_override IS NULL) OR ((niveau_confiance_override)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[])))),
    CONSTRAINT ck_mesures_ressource_horaires_periode_coherente CHECK (((valide_au IS NULL) OR (valide_au > valide_du))),
    CONSTRAINT ck_mesures_ressource_horaires_statut_valide CHECK (((statut)::text = ANY ((ARRAY['brut'::character varying, 'valide_auto'::character varying, 'valide_humain'::character varying, 'publie'::character varying, 'deprecie'::character varying])::text[])))
);


--
-- Name: TABLE mesures_ressource_horaires; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.mesures_ressource_horaires IS 'Mesures horaires ingerees depuis sources externes (NASA POWER, Vague 3). Pendant horaire de mesures_ressource (journalier) et mesures_ressource_mensuelles (mensuel). instant_mesure en TIMESTAMPTZ (UTC) pour le controle qualite horaire (position solaire sans ambiguite de fuseau). Versioning temporel par (valide_du, valide_au) + EXCLUDE BTree-GiST sur identite metier (serie_id, instant_mesure). Statut editorial et niveau de confiance derive/override par couche service editoriale.';


--
-- Name: mesures_ressource_horaires_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.mesures_ressource_horaires ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.mesures_ressource_horaires_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: mesures_ressource_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.mesures_ressource ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.mesures_ressource_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: mesures_ressource_mensuelles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mesures_ressource_mensuelles (
    id bigint NOT NULL,
    serie_id bigint NOT NULL,
    annee smallint NOT NULL,
    mois smallint NOT NULL,
    valeur double precision NOT NULL,
    valide_du timestamp with time zone DEFAULT now() NOT NULL,
    valide_au timestamp with time zone,
    statut character varying(16) DEFAULT 'brut'::character varying NOT NULL,
    niveau_confiance_derive character varying(1) NOT NULL,
    niveau_confiance_override character varying(1),
    commentaire_editorial text,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_mesures_ressource_mensuelles_annee_valide CHECK (((annee >= 1981) AND (annee <= 2099))),
    CONSTRAINT ck_mesures_ressource_mensuelles_mois_valide CHECK (((mois >= 1) AND (mois <= 12))),
    CONSTRAINT ck_mesures_ressource_mensuelles_niveau_confiance_derive_valide CHECK (((niveau_confiance_derive)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[]))),
    CONSTRAINT ck_mesures_ressource_mensuelles_niveau_confiance_overri_f9c9 CHECK (((niveau_confiance_override IS NULL) OR ((niveau_confiance_override)::text = ANY ((ARRAY['A'::character varying, 'B'::character varying, 'C'::character varying])::text[])))),
    CONSTRAINT ck_mesures_ressource_mensuelles_periode_coherente CHECK (((valide_au IS NULL) OR (valide_au > valide_du))),
    CONSTRAINT ck_mesures_ressource_mensuelles_statut_valide CHECK (((statut)::text = ANY ((ARRAY['brut'::character varying, 'valide_auto'::character varying, 'valide_humain'::character varying, 'publie'::character varying, 'deprecie'::character varying])::text[])))
);


--
-- Name: TABLE mesures_ressource_mensuelles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.mesures_ressource_mensuelles IS 'Mesures mensuelles ingerees depuis sources externes (SARAH-3 ICDR + NASA POWER 1991-2020, etape 1-7a). Pendant mensuel de mesures_ressource (journalier strict, cadrage Q2 phase 1). Versioning temporel par (valide_du, valide_au) + EXCLUDE BTree-GiST sur identite metier (serie_id, annee, mois). Statut editorial et niveau de confiance derive/override par couche service editoriale.';


--
-- Name: mesures_ressource_mensuelles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.mesures_ressource_mensuelles ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.mesures_ressource_mensuelles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: referentiels_calage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.referentiels_calage (
    id bigint NOT NULL,
    code character varying(120) NOT NULL,
    localite_id bigint NOT NULL,
    grandeur_code character varying(50) NOT NULL,
    saison character varying(40) NOT NULL,
    mois bigint[] NOT NULL,
    biais numeric(8,6) NOT NULL,
    provenance text NOT NULL,
    portee text NOT NULL,
    version character varying(20) DEFAULT 'v1'::character varying NOT NULL,
    actif boolean DEFAULT true NOT NULL,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    serie_sol character varying(120) NOT NULL,
    CONSTRAINT ck_referentiels_calage_biais_definissable CHECK ((biais > ('-1'::integer)::numeric))
);


--
-- Name: TABLE referentiels_calage; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.referentiels_calage IS 'Referentiel de calage satellite/sol : biais saisonniers mesures aux stations de reference, publies avec provenance et portee de transport (ADR-0004).';


--
-- Name: referentiels_calage_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.referentiels_calage ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.referentiels_calage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: series_metadonnees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.series_metadonnees (
    id bigint NOT NULL,
    code character varying(80) NOT NULL,
    libelle text NOT NULL,
    localite_id bigint NOT NULL,
    grandeur_code character varying(80) NOT NULL,
    source_id bigint NOT NULL,
    periode_debut date NOT NULL,
    periode_fin date,
    methode_collecte character varying(40),
    methode_collecte_doc text,
    commentaire_editorial text,
    url_documentation text,
    actif boolean DEFAULT true NOT NULL,
    desactive_le timestamp with time zone,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    granularite character varying(16),
    note_publique text,
    CONSTRAINT ck_series_metadonnees_actif_desactive_coherent CHECK ((((actif = true) AND (desactive_le IS NULL)) OR ((actif = false) AND (desactive_le IS NOT NULL)))),
    CONSTRAINT ck_series_metadonnees_granularite_valide CHECK (((granularite IS NULL) OR ((granularite)::text = ANY ((ARRAY['journalier'::character varying, 'mensuel'::character varying, 'horaire'::character varying])::text[])))),
    CONSTRAINT ck_series_metadonnees_methode_collecte_valide CHECK (((methode_collecte IS NULL) OR ((methode_collecte)::text = ANY ((ARRAY['mesure_directe'::character varying, 'modele_satellitaire'::character varying, 'interpolation_geographique'::character varying, 'extrapolation_temporelle'::character varying, 'calcul_derive'::character varying, 'expertise_humaine'::character varying])::text[])))),
    CONSTRAINT ck_series_metadonnees_periode_coherente CHECK (((periode_fin IS NULL) OR (periode_fin >= periode_debut)))
);


--
-- Name: TABLE series_metadonnees; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.series_metadonnees IS 'Referentiel editorial des series de mesures Kuma. Une serie = un triplet (localite, grandeur, source) avec ses metadonnees editoriales communes.';


--
-- Name: COLUMN series_metadonnees.code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.series_metadonnees.code IS 'Cle naturelle metier (ASCII pur, snake_case). Convention : <localite>_<grandeur>_<source>[_<periode>] ex. gin_conakry_hep_nasa_power_2010_2024.';


--
-- Name: COLUMN series_metadonnees.grandeur_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.series_metadonnees.grandeur_code IS 'FK vers grandeurs_referentiel.code (colonne UNIQUE non-PK). Lisibilite metier prioritaire sur convention SQL classique.';


--
-- Name: COLUMN series_metadonnees.periode_fin; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.series_metadonnees.periode_fin IS 'NULL si la serie est en cours (pas de fin annoncee). Sinon date de la derniere mesure attendue, >= periode_debut.';


--
-- Name: COLUMN series_metadonnees.methode_collecte; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.series_metadonnees.methode_collecte IS 'Methode dominante de collecte de la serie. Liste indicative des 6 valeurs en spec mecaniques-transverses sec. 6.4. CHECK formel pose en 1-2b.';


--
-- Name: COLUMN series_metadonnees.granularite; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.series_metadonnees.granularite IS 'Discriminant de granularite temporelle pour le routage table-cible (journalier/mensuel/horaire). NULL pour les series kuma_calculs (routees par source vers grandeurs_metier ; temporalite portee par grandeurs_metier.periode_type). Resout D-36 (Vague 3 lot 1).';


--
-- Name: COLUMN series_metadonnees.note_publique; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.series_metadonnees.note_publique IS 'Passeport public de la série (servi par l''API sous l''alias notes_fr, affiché sur les fiches du site). Auto-portant : aucune référence de chantier interne. Toute nouvelle série doit le renseigner à l''insertion ; commentaire_editorial reste le journal interne, assaini à l''export d''édition.';


--
-- Name: series_metadonnees_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.series_metadonnees ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.series_metadonnees_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    id bigint NOT NULL,
    code character varying(100) NOT NULL,
    titre text NOT NULL,
    auteurs text[],
    organisation character varying(255),
    type_source character varying(50) NOT NULL,
    annee_publication integer,
    date_consultation date,
    url text,
    doi character varying(255),
    isbn character varying(50),
    metadonnees jsonb,
    fiabilite character varying(20),
    langue character varying(2),
    notes text,
    actif boolean DEFAULT true NOT NULL,
    desactive_le timestamp with time zone,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_sources_actif_desactive_le CHECK ((((actif = true) AND (desactive_le IS NULL)) OR ((actif = false) AND (desactive_le IS NOT NULL)))),
    CONSTRAINT ck_sources_annee_publication_valide CHECK (((annee_publication IS NULL) OR ((annee_publication >= 1900) AND (annee_publication <= 2100)))),
    CONSTRAINT ck_sources_doi_format CHECK (((doi IS NULL) OR ((doi)::text ~ '^10\.[0-9]{4,}(\.[0-9]+)*/[^\s]+$'::text))),
    CONSTRAINT ck_sources_fiabilite_valide CHECK (((fiabilite IS NULL) OR ((fiabilite)::text = ANY ((ARRAY['haute'::character varying, 'moyenne'::character varying, 'faible'::character varying])::text[])))),
    CONSTRAINT ck_sources_isbn_format CHECK (((isbn IS NULL) OR ((isbn)::text ~ '^(97[89][0-9]{10}|[0-9]{9}[0-9X])$'::text))),
    CONSTRAINT ck_sources_langue_format_iso6391 CHECK (((langue IS NULL) OR ((langue)::text ~ '^[a-z]{2}$'::text))),
    CONSTRAINT ck_sources_metadonnees_objet CHECK (((metadonnees IS NULL) OR (jsonb_typeof(metadonnees) = 'object'::text))),
    CONSTRAINT ck_sources_type_source_valide CHECK (((type_source)::text = ANY ((ARRAY['rapport'::character varying, 'article_scientifique'::character varying, 'texte_legal'::character varying, 'communique'::character varying, 'page_web'::character varying, 'base_donnees'::character varying, 'livre'::character varying, 'chapitre_livre'::character varying, 'these'::character varying, 'norme_technique'::character varying, 'auteur_kuma'::character varying])::text[]))),
    CONSTRAINT ck_sources_url_format CHECK (((url IS NULL) OR (url ~ '^https?://[^\s]+$'::text)))
);


--
-- Name: COLUMN sources.code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sources.code IS 'Identifiant court unique. Convention : <organisme>_<theme>[_<annee>]. Ex: irena_lcoe_2024, bcrg_rapport_annuel_2023, iso_50001_2018. Pour les publications recurrentes, inclure l''annee.';


--
-- Name: COLUMN sources.type_source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sources.type_source IS '11 valeurs autorisees : rapport, article_scientifique, texte_legal, communique, page_web, base_donnees, livre, chapitre_livre, these, norme_technique (10 valeurs documentaires externes initiales, migration 004) + auteur_kuma (couche editoriale interne Kuma, introduite en 1-5D-i pour la source synthetique kuma_calculs).';


--
-- Name: COLUMN sources.doi; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sources.doi IS 'Digital Object Identifier (ISO 26324). Stocke sans prefixe URL. Ex: 10.1038/nature12373 (pas https://doi.org/10.1038/nature12373).';


--
-- Name: COLUMN sources.isbn; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sources.isbn IS 'International Standard Book Number (ISO 2108). Stocke sans tirets ni espaces. Ex: 9782123456789 (pas 978-2-1234-5678-9). ISBN-10 ou ISBN-13 acceptes.';


--
-- Name: COLUMN sources.fiabilite; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sources.fiabilite IS 'Qualification editoriale Kuma (3 niveaux). Voir docs/architecture/04-api.md pour le mapping editorial complet.';


--
-- Name: COLUMN sources.langue; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.sources.langue IS 'Code ISO 639-1 (2 lettres minuscules). Ex: fr, en, ar, pt, sw, yo, wo.';


--
-- Name: sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.sources ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.sources_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: unites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unites (
    id bigint NOT NULL,
    code character varying(80) NOT NULL,
    libelle text NOT NULL,
    symbole character varying(50) NOT NULL,
    grandeur character varying(100) NOT NULL,
    systeme character varying(20) NOT NULL,
    est_unite_de_base boolean DEFAULT false NOT NULL,
    facteur_conversion_si numeric(60,30) DEFAULT 1 NOT NULL,
    decalage_conversion_si numeric(60,30) DEFAULT 0 NOT NULL,
    code_unite_si character varying(80) NOT NULL,
    note_methodologique text,
    contexte_usage text,
    references_normatives text[],
    actif boolean DEFAULT true NOT NULL,
    desactive_le timestamp with time zone,
    cree_le timestamp with time zone DEFAULT now() NOT NULL,
    cree_par bigint,
    modifie_le timestamp with time zone DEFAULT now() NOT NULL,
    modifie_par bigint,
    CONSTRAINT ck_unites_actif_desactive_le CHECK ((((actif = true) AND (desactive_le IS NULL)) OR ((actif = false) AND (desactive_le IS NOT NULL)))),
    CONSTRAINT ck_unites_base_coherence_systeme CHECK ((((est_unite_de_base = true) AND ((systeme)::text = 'SI'::text)) OR (est_unite_de_base = false))),
    CONSTRAINT ck_unites_systeme_valide CHECK (((systeme)::text = ANY ((ARRAY['SI'::character varying, 'non_SI_acceptee'::character varying, 'composee_mixte'::character varying, 'imperial'::character varying, 'autre'::character varying])::text[])))
);


--
-- Name: TABLE unites; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.unites IS 'Référentiel des unités de mesure de Kuma Data Core. 153 unités sur 30 grandeurs, validées contre 20+ organismes normatifs internationaux (BIPM, AIE, ONU, NIST, IUPAC, IEC, DIN, ISO, IPCC, IRENA, UNECE, etc.).';


--
-- Name: unites_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.unites ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.unites_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: v_grandeurs_metier_courantes; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_grandeurs_metier_courantes AS
 SELECT gm.id,
    gm.grandeur_code,
    gm.localite_id,
    gm.series_metadonnees_id,
    gm.periode_type,
    gm.annee_debut,
    gm.annee_fin,
    gm.mois,
    gm.version_formule,
    gm.valeur,
    gm.valide_du,
    gm.valide_au,
    gm.statut,
    gm.niveau_confiance_derive,
    gm.niveau_confiance_override,
    COALESCE(gm.niveau_confiance_override, gm.niveau_confiance_derive) AS niveau_effectif,
    gm.commentaire_editorial,
    gm.cree_le,
    gm.cree_par,
    gm.modifie_le,
    gm.modifie_par
   FROM (public.grandeurs_metier gm
     JOIN public.grandeurs_referentiel gr ON (((gr.code)::text = (gm.grandeur_code)::text)))
  WHERE ((gm.valide_au IS NULL) AND (gm.version_formule = gr.version_formule_actuelle) AND ((gm.statut)::text <> 'deprecie'::text));


--
-- Name: VIEW v_grandeurs_metier_courantes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_grandeurs_metier_courantes IS 'Vue projetant les lignes courantes de grandeurs_metier (valide_au IS NULL) en version de formule actuelle (version_formule = grandeurs_referentiel.version_formule_actuelle) et hors statut deprecie. Ajoute la colonne calculee niveau_effectif = COALESCE(niveau_confiance_override, niveau_confiance_derive). Equivalent SQL de l''hybrid_property GrandeurMetier.niveau_effectif. Cf. spec 1-5 sec. 4.';


--
-- Name: v_mesures_avec_niveau_effectif; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_mesures_avec_niveau_effectif AS
 SELECT id,
    serie_id,
    instant_mesure,
    valeur,
    valide_du,
    valide_au,
    statut,
    niveau_confiance_derive,
    niveau_confiance_override,
    COALESCE(niveau_confiance_override, niveau_confiance_derive) AS niveau_effectif,
    commentaire_editorial,
    cree_le,
    cree_par,
    modifie_le,
    modifie_par
   FROM public.mesures_ressource m;


--
-- Name: VIEW v_mesures_avec_niveau_effectif; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON VIEW public.v_mesures_avec_niveau_effectif IS 'Vue projetant mesures_ressource + colonne calculee niveau_effectif = COALESCE(niveau_confiance_override, niveau_confiance_derive). Equivalent SQL de l''hybrid_property MesureRessource.niveau_effectif. Permet d''eviter le scan applicatif Python pour les requetes lecture massives. Cf. spec 1-2b sec. 3.4.';


--
-- Name: grandeurs_metier ex_grandeurs_metier_identite_periode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_metier
    ADD CONSTRAINT ex_grandeurs_metier_identite_periode EXCLUDE USING gist (grandeur_code WITH =, localite_id WITH =, series_metadonnees_id WITH =, periode_type WITH =, annee_debut WITH =, annee_fin WITH =, COALESCE(mois, 0) WITH =, version_formule WITH =, tstzrange(valide_du, valide_au) WITH &&);


--
-- Name: mesures_ressource_horaires ex_mesures_ressource_horaires_identite_periode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_horaires
    ADD CONSTRAINT ex_mesures_ressource_horaires_identite_periode EXCLUDE USING gist (serie_id WITH =, instant_mesure WITH =, tstzrange(valide_du, valide_au) WITH &&);


--
-- Name: mesures_ressource ex_mesures_ressource_identite_periode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource
    ADD CONSTRAINT ex_mesures_ressource_identite_periode EXCLUDE USING gist (serie_id WITH =, instant_mesure WITH =, tstzrange(valide_du, valide_au) WITH &&);


--
-- Name: mesures_ressource_mensuelles ex_mesures_ressource_mensuelles_identite_periode; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_mensuelles
    ADD CONSTRAINT ex_mesures_ressource_mensuelles_identite_periode EXCLUDE USING gist (serie_id WITH =, annee WITH =, mois WITH =, tstzrange(valide_du, valide_au) WITH &&);


--
-- Name: audit_log pk_audit_log; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT pk_audit_log PRIMARY KEY (id);


--
-- Name: calage_couverture pk_calage_couverture; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calage_couverture
    ADD CONSTRAINT pk_calage_couverture PRIMARY KEY (id);


--
-- Name: contributeurs pk_contributeurs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contributeurs
    ADD CONSTRAINT pk_contributeurs PRIMARY KEY (id);


--
-- Name: grandeurs_metier pk_grandeurs_metier; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_metier
    ADD CONSTRAINT pk_grandeurs_metier PRIMARY KEY (id);


--
-- Name: grandeurs_referentiel pk_grandeurs_referentiel; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_referentiel
    ADD CONSTRAINT pk_grandeurs_referentiel PRIMARY KEY (id);


--
-- Name: localites pk_localites; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.localites
    ADD CONSTRAINT pk_localites PRIMARY KEY (id);


--
-- Name: mesures_ressource pk_mesures_ressource; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource
    ADD CONSTRAINT pk_mesures_ressource PRIMARY KEY (id);


--
-- Name: mesures_ressource_horaires pk_mesures_ressource_horaires; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_horaires
    ADD CONSTRAINT pk_mesures_ressource_horaires PRIMARY KEY (id);


--
-- Name: mesures_ressource_mensuelles pk_mesures_ressource_mensuelles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_mensuelles
    ADD CONSTRAINT pk_mesures_ressource_mensuelles PRIMARY KEY (id);


--
-- Name: referentiels_calage pk_referentiels_calage; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.referentiels_calage
    ADD CONSTRAINT pk_referentiels_calage PRIMARY KEY (id);


--
-- Name: series_metadonnees pk_series_metadonnees; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT pk_series_metadonnees PRIMARY KEY (id);


--
-- Name: sources pk_sources; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT pk_sources PRIMARY KEY (id);


--
-- Name: unites pk_unites; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unites
    ADD CONSTRAINT pk_unites PRIMARY KEY (id);


--
-- Name: calage_couverture uq_calage_couverture_referentiel_localite_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calage_couverture
    ADD CONSTRAINT uq_calage_couverture_referentiel_localite_version UNIQUE (referentiel_code, localite_id, version);


--
-- Name: contributeurs uq_contributeurs_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contributeurs
    ADD CONSTRAINT uq_contributeurs_code UNIQUE (code);


--
-- Name: contributeurs uq_contributeurs_email_principal; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contributeurs
    ADD CONSTRAINT uq_contributeurs_email_principal UNIQUE (email_principal);


--
-- Name: grandeurs_referentiel uq_grandeurs_referentiel_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_referentiel
    ADD CONSTRAINT uq_grandeurs_referentiel_code UNIQUE (code);


--
-- Name: localites uq_localites_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.localites
    ADD CONSTRAINT uq_localites_code UNIQUE (code);


--
-- Name: referentiels_calage uq_referentiels_calage_station_grandeur_saison_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.referentiels_calage
    ADD CONSTRAINT uq_referentiels_calage_station_grandeur_saison_version UNIQUE (localite_id, grandeur_code, saison, version);


--
-- Name: series_metadonnees uq_series_metadonnees_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT uq_series_metadonnees_code UNIQUE (code);


--
-- Name: series_metadonnees uq_series_metadonnees_identite_metier_plage_granularite; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT uq_series_metadonnees_identite_metier_plage_granularite UNIQUE (localite_id, grandeur_code, source_id, periode_debut, periode_fin, granularite);


--
-- Name: sources uq_sources_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT uq_sources_code UNIQUE (code);


--
-- Name: unites uq_unites_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unites
    ADD CONSTRAINT uq_unites_code UNIQUE (code);


--
-- Name: idx_audit_log_auteur_applicatif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_auteur_applicatif ON public.audit_log USING btree (auteur_applicatif, horodatage DESC) WHERE (auteur_applicatif IS NOT NULL);


--
-- Name: idx_audit_log_horodatage; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_horodatage ON public.audit_log USING btree (horodatage DESC);


--
-- Name: idx_audit_log_ligne; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_ligne ON public.audit_log USING btree (schema_audite, table_auditee, id_ligne_auditee, horodatage DESC);


--
-- Name: idx_audit_log_table_horodatage; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_table_horodatage ON public.audit_log USING btree (schema_audite, table_auditee, horodatage DESC);


--
-- Name: idx_audit_log_utilisateur_pg; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_utilisateur_pg ON public.audit_log USING btree (utilisateur_pg, horodatage DESC);


--
-- Name: idx_calage_couverture_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calage_couverture_actif ON public.calage_couverture USING btree (actif);


--
-- Name: idx_calage_couverture_referentiel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_calage_couverture_referentiel ON public.calage_couverture USING btree (referentiel_code);


--
-- Name: idx_contributeurs_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_contributeurs_actif ON public.contributeurs USING btree (actif);


--
-- Name: idx_contributeurs_pays_iso3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_contributeurs_pays_iso3 ON public.contributeurs USING btree (pays_iso3);


--
-- Name: idx_contributeurs_statut; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_contributeurs_statut ON public.contributeurs USING btree (statut);


--
-- Name: idx_contributeurs_type_contributeur; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_contributeurs_type_contributeur ON public.contributeurs USING btree (type_contributeur);


--
-- Name: idx_grandeurs_metier_courantes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_grandeurs_metier_courantes ON public.grandeurs_metier USING btree (grandeur_code, localite_id, periode_type, annee_debut, annee_fin, mois, version_formule) WHERE (valide_au IS NULL);


--
-- Name: idx_grandeurs_referentiel_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_grandeurs_referentiel_actif ON public.grandeurs_referentiel USING btree (actif);


--
-- Name: idx_localites_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_localites_actif ON public.localites USING btree (actif);


--
-- Name: idx_localites_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_localites_parent_id ON public.localites USING btree (parent_id);


--
-- Name: idx_localites_pays_iso3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_localites_pays_iso3 ON public.localites USING btree (pays_iso3);


--
-- Name: idx_localites_type_localite; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_localites_type_localite ON public.localites USING btree (type_localite);


--
-- Name: idx_mesures_ressource_courantes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mesures_ressource_courantes ON public.mesures_ressource USING btree (serie_id, instant_mesure) WHERE (valide_au IS NULL);


--
-- Name: idx_mesures_ressource_horaires_courantes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mesures_ressource_horaires_courantes ON public.mesures_ressource_horaires USING btree (serie_id, instant_mesure) WHERE (valide_au IS NULL);


--
-- Name: idx_mesures_ressource_mensuelles_courantes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_mesures_ressource_mensuelles_courantes ON public.mesures_ressource_mensuelles USING btree (serie_id, annee, mois) WHERE (valide_au IS NULL);


--
-- Name: idx_referentiels_calage_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_referentiels_calage_actif ON public.referentiels_calage USING btree (actif);


--
-- Name: idx_referentiels_calage_localite_grandeur; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_referentiels_calage_localite_grandeur ON public.referentiels_calage USING btree (localite_id, grandeur_code);


--
-- Name: idx_series_metadonnees_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_series_metadonnees_actif ON public.series_metadonnees USING btree (actif);


--
-- Name: idx_series_metadonnees_grandeur_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_series_metadonnees_grandeur_code ON public.series_metadonnees USING btree (grandeur_code);


--
-- Name: idx_series_metadonnees_localite_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_series_metadonnees_localite_id ON public.series_metadonnees USING btree (localite_id);


--
-- Name: idx_series_metadonnees_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_series_metadonnees_source_id ON public.series_metadonnees USING btree (source_id);


--
-- Name: idx_sources_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_actif ON public.sources USING btree (actif);


--
-- Name: idx_sources_annee_publication; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_annee_publication ON public.sources USING btree (annee_publication);


--
-- Name: idx_sources_langue; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_langue ON public.sources USING btree (langue);


--
-- Name: idx_sources_metadonnees_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_metadonnees_gin ON public.sources USING gin (metadonnees);


--
-- Name: idx_sources_organisation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_organisation ON public.sources USING btree (organisation);


--
-- Name: idx_sources_type_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sources_type_source ON public.sources USING btree (type_source);


--
-- Name: idx_unites_actif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_unites_actif ON public.unites USING btree (actif);


--
-- Name: idx_unites_code_unite_si; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_unites_code_unite_si ON public.unites USING btree (code_unite_si);


--
-- Name: idx_unites_est_unite_de_base; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_unites_est_unite_de_base ON public.unites USING btree (est_unite_de_base) WHERE (est_unite_de_base = true);


--
-- Name: idx_unites_grandeur; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_unites_grandeur ON public.unites USING btree (grandeur);


--
-- Name: idx_unites_systeme; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_unites_systeme ON public.unites USING btree (systeme);


--
-- Name: calage_couverture trg_audit_calage_couverture; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_calage_couverture AFTER INSERT OR DELETE OR UPDATE ON public.calage_couverture FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: contributeurs trg_audit_contributeurs; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_contributeurs AFTER INSERT OR DELETE OR UPDATE ON public.contributeurs FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: grandeurs_metier trg_audit_grandeurs_metier; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_grandeurs_metier AFTER INSERT OR DELETE OR UPDATE ON public.grandeurs_metier FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: grandeurs_referentiel trg_audit_grandeurs_referentiel; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_grandeurs_referentiel AFTER INSERT OR DELETE OR UPDATE ON public.grandeurs_referentiel FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: localites trg_audit_localites; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_localites AFTER INSERT OR DELETE OR UPDATE ON public.localites FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: mesures_ressource trg_audit_mesures_ressource; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_mesures_ressource AFTER INSERT OR DELETE OR UPDATE ON public.mesures_ressource FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: mesures_ressource_horaires trg_audit_mesures_ressource_horaires; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_mesures_ressource_horaires AFTER INSERT OR DELETE OR UPDATE ON public.mesures_ressource_horaires FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: mesures_ressource_mensuelles trg_audit_mesures_ressource_mensuelles; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_mesures_ressource_mensuelles AFTER INSERT OR DELETE OR UPDATE ON public.mesures_ressource_mensuelles FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: referentiels_calage trg_audit_referentiels_calage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_referentiels_calage AFTER INSERT OR DELETE OR UPDATE ON public.referentiels_calage FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: series_metadonnees trg_audit_series_metadonnees; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_series_metadonnees AFTER INSERT OR DELETE OR UPDATE ON public.series_metadonnees FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: sources trg_audit_sources; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_sources AFTER INSERT OR DELETE OR UPDATE ON public.sources FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: unites trg_audit_unites; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_audit_unites AFTER INSERT OR DELETE OR UPDATE ON public.unites FOR EACH ROW EXECUTE FUNCTION public.kuma_log_audit();


--
-- Name: localites trg_valider_hierarchie_localites; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_valider_hierarchie_localites BEFORE INSERT OR UPDATE ON public.localites FOR EACH ROW EXECUTE FUNCTION public.valider_hierarchie_localites();


--
-- Name: calage_couverture fk_calage_couverture_localite__localites; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.calage_couverture
    ADD CONSTRAINT fk_calage_couverture_localite__localites FOREIGN KEY (localite_id) REFERENCES public.localites(id);


--
-- Name: contributeurs fk_contributeurs_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contributeurs
    ADD CONSTRAINT fk_contributeurs_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id);


--
-- Name: contributeurs fk_contributeurs_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contributeurs
    ADD CONSTRAINT fk_contributeurs_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id);


--
-- Name: grandeurs_metier fk_grandeurs_metier_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_metier
    ADD CONSTRAINT fk_grandeurs_metier_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: grandeurs_metier fk_grandeurs_metier_grandeur_code__grandeurs_referentiel; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_metier
    ADD CONSTRAINT fk_grandeurs_metier_grandeur_code__grandeurs_referentiel FOREIGN KEY (grandeur_code) REFERENCES public.grandeurs_referentiel(code) ON DELETE RESTRICT;


--
-- Name: grandeurs_metier fk_grandeurs_metier_localite_id__localites; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_metier
    ADD CONSTRAINT fk_grandeurs_metier_localite_id__localites FOREIGN KEY (localite_id) REFERENCES public.localites(id) ON DELETE RESTRICT;


--
-- Name: grandeurs_metier fk_grandeurs_metier_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_metier
    ADD CONSTRAINT fk_grandeurs_metier_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: grandeurs_metier fk_grandeurs_metier_series_metadonnees_id__series_metadonnees; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_metier
    ADD CONSTRAINT fk_grandeurs_metier_series_metadonnees_id__series_metadonnees FOREIGN KEY (series_metadonnees_id) REFERENCES public.series_metadonnees(id) ON DELETE RESTRICT;


--
-- Name: grandeurs_referentiel fk_grandeurs_referentiel_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_referentiel
    ADD CONSTRAINT fk_grandeurs_referentiel_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: grandeurs_referentiel fk_grandeurs_referentiel_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_referentiel
    ADD CONSTRAINT fk_grandeurs_referentiel_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: grandeurs_referentiel fk_grandeurs_referentiel_unite_id__unites; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.grandeurs_referentiel
    ADD CONSTRAINT fk_grandeurs_referentiel_unite_id__unites FOREIGN KEY (unite_id) REFERENCES public.unites(id) ON DELETE RESTRICT;


--
-- Name: localites fk_localites_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.localites
    ADD CONSTRAINT fk_localites_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id);


--
-- Name: localites fk_localites_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.localites
    ADD CONSTRAINT fk_localites_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id);


--
-- Name: localites fk_localites_parent_id__localites; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.localites
    ADD CONSTRAINT fk_localites_parent_id__localites FOREIGN KEY (parent_id) REFERENCES public.localites(id);


--
-- Name: mesures_ressource fk_mesures_ressource_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource
    ADD CONSTRAINT fk_mesures_ressource_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: mesures_ressource_horaires fk_mesures_ressource_horaires_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_horaires
    ADD CONSTRAINT fk_mesures_ressource_horaires_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: mesures_ressource_horaires fk_mesures_ressource_horaires_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_horaires
    ADD CONSTRAINT fk_mesures_ressource_horaires_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: mesures_ressource_horaires fk_mesures_ressource_horaires_serie_id__series_metadonnees; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_horaires
    ADD CONSTRAINT fk_mesures_ressource_horaires_serie_id__series_metadonnees FOREIGN KEY (serie_id) REFERENCES public.series_metadonnees(id) ON DELETE RESTRICT;


--
-- Name: mesures_ressource_mensuelles fk_mesures_ressource_mensuelles_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_mensuelles
    ADD CONSTRAINT fk_mesures_ressource_mensuelles_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: mesures_ressource_mensuelles fk_mesures_ressource_mensuelles_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_mensuelles
    ADD CONSTRAINT fk_mesures_ressource_mensuelles_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: mesures_ressource_mensuelles fk_mesures_ressource_mensuelles_serie_id__series_metadonnees; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource_mensuelles
    ADD CONSTRAINT fk_mesures_ressource_mensuelles_serie_id__series_metadonnees FOREIGN KEY (serie_id) REFERENCES public.series_metadonnees(id) ON DELETE RESTRICT;


--
-- Name: mesures_ressource fk_mesures_ressource_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource
    ADD CONSTRAINT fk_mesures_ressource_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: mesures_ressource fk_mesures_ressource_serie_id__series_metadonnees; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mesures_ressource
    ADD CONSTRAINT fk_mesures_ressource_serie_id__series_metadonnees FOREIGN KEY (serie_id) REFERENCES public.series_metadonnees(id) ON DELETE RESTRICT;


--
-- Name: referentiels_calage fk_referentiels_calage_localite__localites; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.referentiels_calage
    ADD CONSTRAINT fk_referentiels_calage_localite__localites FOREIGN KEY (localite_id) REFERENCES public.localites(id);


--
-- Name: series_metadonnees fk_series_metadonnees_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT fk_series_metadonnees_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: series_metadonnees fk_series_metadonnees_grandeur_code__grandeurs_referentiel; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT fk_series_metadonnees_grandeur_code__grandeurs_referentiel FOREIGN KEY (grandeur_code) REFERENCES public.grandeurs_referentiel(code) ON DELETE RESTRICT;


--
-- Name: series_metadonnees fk_series_metadonnees_localite_id__localites; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT fk_series_metadonnees_localite_id__localites FOREIGN KEY (localite_id) REFERENCES public.localites(id) ON DELETE RESTRICT;


--
-- Name: series_metadonnees fk_series_metadonnees_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT fk_series_metadonnees_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id) ON DELETE SET NULL;


--
-- Name: series_metadonnees fk_series_metadonnees_source_id__sources; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series_metadonnees
    ADD CONSTRAINT fk_series_metadonnees_source_id__sources FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE RESTRICT;


--
-- Name: sources fk_sources_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT fk_sources_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id);


--
-- Name: sources fk_sources_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT fk_sources_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id);


--
-- Name: unites fk_unites_cree_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unites
    ADD CONSTRAINT fk_unites_cree_par__contributeurs FOREIGN KEY (cree_par) REFERENCES public.contributeurs(id);


--
-- Name: unites fk_unites_modifie_par__contributeurs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unites
    ADD CONSTRAINT fk_unites_modifie_par__contributeurs FOREIGN KEY (modifie_par) REFERENCES public.contributeurs(id);


--
-- PostgreSQL database dump complete
--


