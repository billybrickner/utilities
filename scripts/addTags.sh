TAG_FILE=tags
ctags -R -a -o $TAG_FILE --exclude=html --exclude=*.css --exclude=*.js .
ctags -R -a -o $TAG_FILE --languages=python --python-kinds=-iv --exclude=html --exclude=*.css --exclude=*.js .
