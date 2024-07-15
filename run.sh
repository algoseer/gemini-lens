docker run --rm -ti \
    --name gemini-lens \
    -e GOOGLE_API_KEY=<apikeyhere>
    -p 5000:5000 \
    gemini-lens:latest