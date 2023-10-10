from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from youtube_transcript_api import YouTubeTranscriptApi
import openai
import os
from pytube import YouTube
from pydub import AudioSegment
import requests
import uuid



app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')  # for Heroku deployment
if not DATABASE_URL:
    DATABASE_URL = "postgresql://postgres:trinity@123@localhost/recipe_db"

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///recipes.db'
db = SQLAlchemy()
db.init_app(app)

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen?smart_format=true&language=en&model=nova-2-ea"
DEEPGRAM_API_KEY = "c1e595d28689872f3f3275f2c027d8c93a2f6490"

OPENAI_API_KEY = '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'
openai.api_key = OPENAI_API_KEY
    
    

class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_link = db.Column(db.String(500), nullable=False)
    video_title = db.Column(db.String(500), nullable=True)
    thumbnail = db.Column(db.String(500), nullable=True)  
    ingredients = db.Column(db.Text, nullable=False)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        video_link = request.form.get('video_link')

        # Extract video title and thumbnail using pytube
        yt = YouTube(video_link)
        video_title = yt.title
        thumbnail = yt.thumbnail_url

        # Transcribe video and extract ingredients using OpenAI
        ingredients, audio_path, full_transcript = transcribe_and_extract(video_link)
        recipe = Recipe(video_link=video_link, video_title=video_title, thumbnail=thumbnail, ingredients=ingredients)
        db.session.add(recipe)
        db.session.commit()

        # After committing, recipe.id is available
        audio_file_path_mp3 = f"audio_{recipe.id}.mp3"
        # Check if the file already exists, and if so, delete it
        if os.path.exists(audio_file_path_mp3):
             os.remove(audio_file_path_mp3)
        os.rename(audio_path, audio_file_path_mp3)

        transcript_filename = f"transcript_{recipe.id}.txt"
        with open(transcript_filename, "w") as f:
            f.write(full_transcript)  # Assuming full_transcript is returned from transcribe_and_extract

        # Cleanup: Remove temp files
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if os.path.exists(audio_file_path_mp3):
            os.remove(audio_file_path_mp3)
        if os.path.exists("transcript.txt"):
            os.remove("transcript.txt")

        return redirect(url_for('index') + '?done=true')
    recipes = Recipe.query.all()
    return render_template('index.html', recipes=recipes)

@app.route('/download_audio/<int:recipe_id>')
def download_audio(recipe_id):
    # Create a unique filename based on the recipe ID
    audio_filename = f"audio_{recipe_id}.mp3"
    
    # Ensure the audio file exists
    if not os.path.exists(audio_filename):
        return "Audio file not found.", 404

    # Serve the file and then delete it
    with open(audio_filename, "rb") as f:
        audio_data = f.read()

    os.remove(audio_filename)
    return audio_data, 200, {
        "Content-Type": "audio/mp3",
        "Content-Disposition": f"attachment; filename={audio_filename}"
    }

@app.route('/download_transcript/<int:recipe_id>')
def download_transcript(recipe_id):
    # Create a unique filename based on the recipe ID
    transcript_filename = f"transcript_{recipe_id}.txt"
    
    # Ensure the transcript file exists
    if not os.path.exists(transcript_filename):
        return "Transcript not found.", 404

    # Serve the file and then delete it
    with open(transcript_filename, "r") as f:
        transcript_data = f.read()

    os.remove(transcript_filename)
    return transcript_data, 200, {
        "Content-Type": "text/plain",
        "Content-Disposition": f"attachment; filename={transcript_filename}"
    }

def transcribe_and_extract(video_link):
    try:
        # 1. Download audio from YouTube in mp4 format
        yt = YouTube(video_link)
        stream = yt.streams.filter(only_audio=True, file_extension='mp4').first()

        if not stream:
            return "Status: No audio stream in mp4 format available for this video."

        audio_file_path = stream.download(filename=f"temp_audio_{uuid.uuid4()}")
        #return "Status: Audio downloaded successfully."

        # Convert to mp3
        audio = AudioSegment.from_file(audio_file_path, format="mp4")
        audio_file_path_mp3 = f"temp_audio_{uuid.uuid4()}.mp3"
        audio.export(audio_file_path_mp3, format="mp3")
        #return "Status: Audio converted to mp3 format successfully."

        

        # 2. Transcribe audio using Deepgram
        with open(audio_file_path_mp3, "rb") as audio_file:
            headers = {
                "Authorization": f"Token {DEEPGRAM_API_KEY}"
            }
            response = requests.post(DEEPGRAM_API_URL, headers=headers, data=audio_file)
            response_data = response.json()

        if "results" not in response_data:
            return f"Deepgram Error: {response_data.get('message', 'Unknown error')}"

        full_transcript = response_data["results"]["channels"][0]["alternatives"][0]["transcript"]
        
        #transcript_filename = f"transcript_{recipe.id}.txt"
        with open("transcript.txt", "w") as f:
            f.write(full_transcript)

        #3. Get ingredients and recipe steps from OpenAI 
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
            {
                "role": "system",
                "content": "This is a Youtube recipe transcript. Generate a recipe from this transcript that can be easily followed along with all the ingredients and steps. Summarize the ingredients required for the recipe first and then detail out the steps. Ensure you don't miss out on any steps or ingredients by double checking your response before generating the final output."
            },
            {
                "role": "user",
                "content": full_transcript}
                ],
            temperature=1,
            max_tokens=1000,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
            )

        extracted_ingredients = response["choices"][0]["message"]["content"]

        # Split the response into lines and format them into a structured list
        lines = extracted_ingredients.split("\n")
        formatted_ingredients = "|||".join(line.strip() for line in lines if line.strip())

        return f"{formatted_ingredients}", audio_file_path_mp3, full_transcript
    

    except Exception as e:
        return f"An error occurred: {str(e)}"


with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)


    
