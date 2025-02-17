docker run --rm -d \
    --name lenses \
    -v $PWD:/app \
    -e GOOGLE_API_KEY="<your-api-key-here>" \
    -p 4040:8501 \
    --privileged \
    lenses:latest