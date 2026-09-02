# AgGPS Studio

[English](README.md) | [Español](README.es.md) | Português (Brasil)

Envie um **AgGPS.zip** da Trimble e baixe:

1. `<Fazenda>_AgGPS.zip` pronto para copiar no **Case IH AFS Pro 700**
2. `<Fazenda>_Shapefile.zip` como alternativa pronta para copiar
3. Um **PDF** imprimível com mapas de taipas para o operador
4. `<Fazenda>_Mapas_lotes.zip` com um JPG independente por talhão
5. `<Fazenda>_paquete_completo.zip` com todos os arquivos e instruções

Este processo foi carregado com sucesso em um Puma 210 com AFS Pro 700. Ele gera shapefiles 2D seguros para o trator e mantém separados os dois formatos de importação.

## Executar com Docker

```bash
cp .env.example .env
# Defina uma senha longa em AGGPS_STUDIO_PASSWORD.
docker compose up --build --detach
```

Abra `http://localhost:8765`. Em produção, use HTTPS e `COOKIE_SECURE=true`.

## Executar pela linha de comando

Python 3.13 é obrigatório.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python process.py /caminho/AgGPS.zip --out ./saida --no-sat --language pt-BR
```

Os documentos para o operador aceitam `es`, `en` e `pt-BR`. Espanhol é o idioma padrão. Cada ZIP e PDF entregue usa o nome seguro da fazenda como prefixo; por exemplo, `DEMO_FARM_AgGPS.zip`.

## Aplicativo desktop (Windows x64 / Linux x64)

Baixe `aggps-studio-0.4.3-*.zip` (artefatos de CI ou release). Extraia a pasta onedir.

Execute o lançador GUI normal:

- Windows: `AgGPS Studio.exe`
- Linux: `chmod +x "AgGPS Studio" && ./"AgGPS Studio"`

O lançador é `--windowed` (sem console). `--version` e `--smoke-test` funcionam para verificação e saem antes de qualquer GUI.

Linux requer bibliotecas de sistema WebKitGTK/GTK (o bundle são apenas arquivos portáveis de aplicação; não é totalmente estático):

Ubuntu 24.04+ / Debian testing+:

```bash
sudo apt-get update
sudo apt-get install -y gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 gir1.2-gtk-3.0
```

Arch Linux:

```bash
sudo pacman -S --needed webkit2gtk-4.1 gtk3
```

O inicializador usa o backend GTK nativo do ambiente e funciona com Wayland e X11.

Windows: Edge WebView2 Evergreen normalmente está presente em sistemas Windows modernos. Se a GUI falhar com erro de webview, instale o Evergreen a partir da página oficial da Microsoft WebView2 (https://developer.microsoft.com/en-us/microsoft-edge/webview2/). O runtime não é incluído neste pacote.

Construir do fonte (reproduzível):

```bash
python -m pip install -r requirements-build-desktop.txt
python build_desktop.py
# zips em dist/; build usa temp da plataforma para intermediários
```

Veja `BUNDLE_README.txt` dentro de cada bundle e `AGENTS.md`.

## Pacotes USB

Os dois downloads USB não contêm pastas extras nem arquivos de instruções:

```text
DEMO_FARM_AgGPS.zip
  AgGPS/Data/<Grower>/<Farm>/<Field>/...

DEMO_FARM_Shapefile.zip
  Shapefile/<Slug>_Bdy.shp
  Shapefile/<Slug>_Taipa.shp
```

Descompacte um ZIP e copie a única pasta para a raiz do USB:

| Alternativa | A raiz deve conter | Source no Import2 |
|---|---|---|
| `<Fazenda>_AgGPS.zip` | `E:\AgGPS\Data\...` | Non Pro 700 1 |
| `<Fazenda>_Shapefile.zip` | `E:\Shapefile\Plot12_Bdy.shp` | Shapefile |

O método recomendado usa o USB do próprio trator: desligue, retire o USB, deixe a pasta `.cn1` intacta e copie `AgGPS` ou `Shapefile` para a raiz, ao lado de `.cn1`. Nunca formate esse USB, copie arquivos dentro de `.cn1`, copie o ZIP fechado nem coloque os dois formatos juntos. Devolva o mesmo USB, ligue, aguarde a mensagem de cópia interna e abra o Import2.

Se não quiser conectar o USB do trator a um computador, use um segundo pendrive FAT32 de 8–32 GB contendo apenas `AgGPS` ou apenas `Shapefile`. Deixe o Pro 700 copiar os arquivos, desligue e recoloque o USB `.cn1` antes de abrir o Import2. Sem `.cn1`, Grower/Farm/Field podem não aparecer.

Importe `*_Bdy` como **Boundary** e depois `*_Taipa` como **Guidance / Line / Multiswath**. A seleção automática funciona somente quando o trator está fisicamente dentro do polígono Boundary. Uma reinicialização adicional depois da importação pode ser normal.

`<Fazenda>_Mapas_lotes.zip` contém arquivos planos como `Plot12.jpg`, um por talhão com Boundary e taipas sobre a imagem de satélite. `<Fazenda>_paquete_completo.zip` contém os dois ZIPs do trator, o PDF, o ZIP de imagens, `LEAME.txt` e `INDICE_CAMPOS.txt`.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python process.py --help
```

Os testes criam shapefiles 2D sintéticos. Não adicione exportações de clientes nem arquivos de campo gerados ao repositório.
