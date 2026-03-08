FROM python:3.11-slim

# Создаем пользователя с ID 1000, как того требует Hugging Face
RUN useradd -m -u 1000 user

# Переключаемся на пользователя
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Копируем список зависимостей и устанавливаем их
COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Копируем весь остальной код
COPY --chown=user . /app

# Устанавливаем переменную окружения для небуферизованного вывода
ENV PYTHONUNBUFFERED=1

# Запуск бота
CMD ["python", "main.py"]
