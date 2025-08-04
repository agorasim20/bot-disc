import discord
from discord.ext import commands
import os
import random
import json
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Cargar diccionarios de palabras desde archivo JSON
def cargar_palabras():
    try:
        with open('palabras.json', 'r', encoding='utf-8') as archivo:
            return json.load(archivo)
    except FileNotFoundError:
        print("❌ Error: No se encontró el archivo 'palabras.json'")
        return {}
    except json.JSONDecodeError:
        print("❌ Error: El archivo 'palabras.json' tiene formato inválido")
        return {}

DICCIONARIOS = cargar_palabras()

# Verificar que se cargaron las palabras correctamente
if not DICCIONARIOS:
    print("❌ No se pudieron cargar las categorías de palabras. Verifica que existe 'palabras.json'")
    exit(1)
else:
    print(f"✅ Cargadas {len(DICCIONARIOS)} categorías de palabras: {', '.join(DICCIONARIOS.keys())}")

# Estructura para manejar sesiones de polls activas
polls_activas = {}

async def procesar_poll(session_id):
    """Procesa una poll y muestra botón para revelar respuestas"""
    if session_id not in polls_activas:
        return
    
    session = polls_activas[session_id]
    session['activa'] = False
    
    canal_destino = session['canal_destino']
    respuestas = session['respuestas']
    
    if not respuestas:
        await canal_destino.send("📊 **Poll finalizada** - No se recibieron respuestas 😢")
        del polls_activas[session_id]
        return
    
    # Crear botón para revelar resultados
    class RevealButton(discord.ui.View):
        def __init__(self, session_id):
            super().__init__(timeout=None)  # Sin timeout para que el botón no expire
            self.session_id = session_id
        
        @discord.ui.button(label='📝 Mostrar Resumen', style=discord.ButtonStyle.secondary)
        async def mostrar_resumen(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.session_id not in polls_activas:
                await interaction.response.send_message("❌ Esta sesión de poll ya no está disponible.", ephemeral=True)
                return
            
            session = polls_activas[self.session_id]
            respuestas = session['respuestas']
            usuarios = session['usuarios']
            
            # Mostrar resumen de respuestas
            resumen = "📝 **Resumen de respuestas:**\n"
            for user_id, respuesta in respuestas.items():
                usuario = discord.utils.get(usuarios, id=user_id)
                if usuario:
                    resumen += f"🔸 **{usuario.display_name}:** {respuesta}\n"
            
            await interaction.response.send_message(resumen)
            
            # Deshabilitar el botón después de usarlo
            button.disabled = True
            button.label = "✅ Resumen Mostrado"
            await interaction.edit_original_response(view=self)
            
            # Limpiar la sesión
            del polls_activas[self.session_id]
    
    # Primero crear y enviar las polls de Discord
    usuarios = session['usuarios']
    usuarios_conectados_actuales = [member for member in session['canal_voz'].members if not member.bot]
    respuestas_unicas = list(set(respuestas.values()))
    
    await canal_destino.send(f"🎭 **¡Revelando resultados!** Se recibieron {len(respuestas)} respuestas. Creando votaciones...")
    
    for i, respuesta in enumerate(respuestas_unicas, 1):
        # Crear título usando una respuesta aleatoria diferente o la pregunta
        if len(respuestas_unicas) > 1:
            otras_respuestas = [r for r in respuestas_unicas if r != respuesta]
            titulo = f"¿Quién dijo: '{random.choice(otras_respuestas)}'?" if otras_respuestas else f"Poll {i}"
        else:
            titulo = f"¿Quién dijo: '{respuesta}'?"
        
        # Crear opciones con los nombres de usuarios conectados
        opciones = [usuario.display_name for usuario in usuarios_conectados_actuales]
        
        if len(opciones) > 10:  # Discord limita a 10 opciones
            opciones = opciones[:10]
        
        # Crear y enviar la poll
        if len(opciones) >= 2:
            try:
                poll = discord.Poll(
                    question=titulo,
                    multiple=False,
                    duration=timedelta(hours=1)  # Duración mínima permitida por Discord
                )
                
                for opcion in opciones:
                    poll.add_answer(text=opcion)
                
                await canal_destino.send(poll=poll)
                await asyncio.sleep(2)  # Pausa entre polls para no saturar
                
            except Exception as e:
                await canal_destino.send(f"❌ Error creando poll para '{respuesta}': {str(e)}")
    
    # Después de crear todas las polls, enviar el botón para mostrar el resumen
    view = RevealButton(session_id)
    mensaje = f"🎭 **Polls creadas!** Presiona el botón cuando quieras ver el resumen de respuestas"
    
    await canal_destino.send(mensaje, view=view)

# Configurar intents (permisos del bot)
intents = discord.Intents.default()
intents.message_content = True  # Habilitado para leer contenido de mensajes
intents.voice_states = True  # Habilitado para detectar estados de voz
intents.guilds = True  # Habilitado para acceder a información de servidores

# Crear el bot
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    """Se ejecuta cuando el bot se conecta exitosamente"""
    print(f'{bot.user} se ha conectado a Discord!')
    print('Bot listo para usar comandos con prefijo !')

@bot.event
async def on_message(message):
    """Responde a mensajes que mencionen al bot y captura respuestas de polls"""
    # Evitar que el bot responda a sí mismo
    if message.author == bot.user:
        return
    
    # Verificar si es una respuesta de poll por mensaje directo
    if isinstance(message.channel, discord.DMChannel):
        await manejar_respuesta_poll(message)
        return
    
    # Procesar comandos normales
    await bot.process_commands(message)

async def manejar_respuesta_poll(message):
    """Maneja las respuestas de poll enviadas por mensaje directo"""
    usuario = message.author
    contenido = message.content.strip()
    
    # Buscar sesiones activas donde este usuario esté participando
    for session_id, session in polls_activas.items():
        if not session['activa']:
            continue
            
        # Verificar si el usuario está en la lista de participantes
        if any(u.id == usuario.id for u in session['usuarios']):
            # Verificar si ya respondió
            if usuario.id in session['respuestas']:
                await message.reply("⚠️ Ya enviaste tu respuesta para esta poll. Solo se toma en cuenta la primera.")
                return
            
            # Verificar que aún esté en tiempo
            if datetime.now() > session['tiempo_limite']:
                await message.reply("⏰ El tiempo para responder ya terminó.")
                return
            
            # Guardar la respuesta
            session['respuestas'][usuario.id] = contenido
            await message.reply(f"✅ **Respuesta registrada:** {contenido}\n🕐 Esperando que termine el tiempo...")
            return
    
    # Si llegamos aquí, no hay polls activas para este usuario
    # No hacer nada para no interferir con otros usos del bot

# Comandos con prefijo !
@bot.command(name='ping')
async def ping_command(ctx):
    """Comando !ping"""
    latency = round(bot.latency * 1000)
    await ctx.send(f'🏓 Pong! Latencia: {latency}ms')

@bot.command(name='recargar_palabras')
async def recargar_palabras_command(ctx):
    """Comando !recargar_palabras"""
    global DICCIONARIOS
    
    try:
        DICCIONARIOS = cargar_palabras()
        if DICCIONARIOS:
            categorias = ", ".join(DICCIONARIOS.keys())
            await ctx.send(f"✅ **Palabras recargadas exitosamente**\n📚 Categorías: {categorias}")
        else:
            await ctx.send("❌ **Error al recargar palabras**\nVerifica que el archivo 'palabras.json' existe y tiene formato válido")
    except Exception as e:
        await ctx.send(f"❌ **Error al recargar palabras:** {str(e)}")

@bot.command(name='ayuda')
async def ayuda_command(ctx):
    """Comando !ayuda"""
    categorias_disponibles = ", ".join(DICCIONARIOS.keys()) if DICCIONARIOS else "ninguna"
    
    ayuda_text = f"""
**Comandos disponibles:**
🔹 `!ping` - Latencia del bot
🔹 `!juego <canal> <categoria>` - Inicia juego en canal de voz
🔹 `!categorias` - Ver categorías de palabras disponibles
🔹 `!recargar_palabras` - Recarga palabras desde JSON
🔹 `!poll <canal> "pregunta" <tiempo>` - Crea poll con respuestas por MD

**Categorías:** {categorias_disponibles}

**📊 Cómo usar !poll:**
1. `!poll #canal "¿Pregunta?" 30` (30 segundos para responder)
2. Los usuarios en voz reciben MD pidiendo respuesta
3. Responden por mensaje directo al bot
4. Tras el tiempo, se crean automáticamente las votaciones de Discord
5. Aparece un botón "📝 Mostrar Resumen" para ver las respuestas originales

**Ejemplos:**
🔹 `!juego General animales`
🔹 `!poll General "¿Cuál es tu color favorito?" 60`
    """
    await ctx.send(ayuda_text)

@bot.command(name='categorias')
async def categorias_command(ctx):
    """Comando !categorias"""
    if not DICCIONARIOS:
        await ctx.send("❌ No hay categorías cargadas. Verifica el archivo 'palabras.json'")
        return
        
    mensaje = "📚 **Categorías disponibles para el juego:**\n\n"
    
    for categoria, palabras in DICCIONARIOS.items():
        ejemplo_palabras = ", ".join(palabras[:3])  # Mostrar solo 3 ejemplos
        mensaje += f"🔹 **{categoria.title()}** ({len(palabras)} palabras) - Ejemplos: {ejemplo_palabras}...\n"
    
    mensaje += f"\n🎮 **Uso:** `!juego #canal categoria`\n"
    mensaje += f"📝 **Ejemplo:** `!juego General animales`"
    
    await ctx.send(mensaje)

@bot.command(name='juego')
async def juego_command(ctx, canal_voz: discord.VoiceChannel = None, categoria: str = "animales"):
    """Comando !juego"""
    
    if canal_voz is None:
        # Si no se especifica canal, buscar en qué canal está el usuario
        if ctx.author.voice and ctx.author.voice.channel:
            canal_voz = ctx.author.voice.channel
        else:
            await ctx.send("❌ Especifica un canal de voz o únete a uno.\nEjemplo: `!juego General animales`")
            return
    
    # Verificar que la categoría existe
    if categoria.lower() not in DICCIONARIOS:
        categorias_disponibles = ", ".join(DICCIONARIOS.keys())
        await ctx.send(f"❌ Categoría '{categoria}' no encontrada.\n📚 Categorías disponibles: {categorias_disponibles}")
        return
    
    # Obtener usuarios conectados al canal de voz
    usuarios_conectados = [member for member in canal_voz.members if not member.bot]
    
    if len(usuarios_conectados) < 2:
        await ctx.send("❌ Necesitas al menos 2 personas en el canal de voz para jugar.")
        return
    
    # Seleccionar palabras de la categoría
    palabras_categoria = DICCIONARIOS[categoria.lower()]
    
    # Seleccionar aleatoriamente una palabra para la mayoría y una especial para el impostor
    palabra_normal = random.choice(palabras_categoria)
    palabra_impostor = random.choice([p for p in palabras_categoria if p != palabra_normal])
    
    # Seleccionar aleatoriamente quién será el impostor
    impostor = random.choice(usuarios_conectados)
    
    # Contar usuarios a los que se enviaron mensajes
    enviados = 0
    errores = []
    
    # Enviar mensajes privados
    for usuario in usuarios_conectados:
        try:
            if usuario == impostor:
                await usuario.send(f"🔴 **IMPOSTOR** 🔴")
            else:
                await usuario.send(f"🔵 **Tu palabra es: {palabra_normal}** 🔵\n📚 Categoría: {categoria.title()}")
            enviados += 1
        except discord.Forbidden:
            errores.append(usuario.display_name)
        except Exception as e:
            errores.append(f"{usuario.display_name} (error: {str(e)})")
    
    # Responder con el resultado (sin revelar las palabras)
    resultado = f"🎮 **Juego iniciado en {canal_voz.name}**\n"
    resultado += f"📚 Categoría: **{categoria.title()}**\n"
    resultado += f"👥 Usuarios en llamada: {len(usuarios_conectados)}\n"
    resultado += f"✅ Mensajes enviados: {enviados}\n"
    
    if errores:
        resultado += f"❌ No se pudo enviar a: {', '.join(errores)}\n"
    
    resultado += f"\n🎯 **El impostor ha sido seleccionado secretamente**"
    
    await ctx.send(resultado)

@bot.command(name='poll')
async def poll_command(ctx, canal_voz: discord.VoiceChannel = None, *, pregunta_y_tiempo: str = None):
    """Inicia una sesión de poll donde usuarios envían respuestas por MD"""
    
    if pregunta_y_tiempo is None:
        await ctx.send("❌ **Uso:** `!poll #canal \"pregunta\" tiempo`\n📝 **Ejemplo:** `!poll General \"¿Cuál es tu color favorito?\" 30`")
        return
    
    # Intentar extraer pregunta y tiempo del texto
    import re
    
    # Buscar texto entre comillas para la pregunta
    match_pregunta = re.search(r'"([^"]*)"', pregunta_y_tiempo)
    if match_pregunta:
        pregunta = match_pregunta.group(1)
        resto = pregunta_y_tiempo.replace(f'"{pregunta}"', '').strip()
        
        # Buscar número para el tiempo
        match_tiempo = re.search(r'\d+', resto)
        tiempo = int(match_tiempo.group()) if match_tiempo else 30
    else:
        # Si no hay comillas, tomar todo menos el último número como pregunta
        partes = pregunta_y_tiempo.rsplit(' ', 1)
        if len(partes) == 2 and partes[1].isdigit():
            pregunta = partes[0]
            tiempo = int(partes[1])
        else:
            pregunta = pregunta_y_tiempo
            tiempo = 30
    
    if canal_voz is None:
        # Si no se especifica canal, buscar en qué canal está el usuario
        if ctx.author.voice and ctx.author.voice.channel:
            canal_voz = ctx.author.voice.channel
        else:
            await ctx.send("❌ Especifica un canal de voz o únete a uno.")
            return
    
    # Validar parámetros
    if tiempo < 10 or tiempo > 300:
        await ctx.send("❌ El tiempo debe estar entre 10 y 300 segundos (5 minutos)")
        return
    
    # Obtener usuarios conectados al canal de voz
    usuarios_conectados = [member for member in canal_voz.members if not member.bot]
    
    if len(usuarios_conectados) < 2:
        await ctx.send("❌ Necesitas al menos 2 personas en el canal de voz para hacer una poll.")
        return
    
    # Crear ID único para la sesión
    session_id = f"{ctx.guild.id}_{canal_voz.id}_{int(datetime.now().timestamp())}"
    
    # Configurar la sesión de poll
    polls_activas[session_id] = {
        'canal_voz': canal_voz,
        'usuarios': usuarios_conectados,
        'pregunta': pregunta,
        'respuestas': {},  # {user_id: respuesta}
        'canal_destino': ctx.channel,
        'tiempo_limite': datetime.now() + timedelta(seconds=tiempo),
        'activa': True
    }
    
    # Enviar instrucciones a los usuarios
    enviados = 0
    errores = []
    
    for usuario in usuarios_conectados:
        try:
            await usuario.send(
                f"📊 **POLL INICIADA** 📊\n"
                f"❓ **Pregunta:** {pregunta}\n"
                f"⏰ **Tiempo límite:** {tiempo} segundos\n\n"
                f"📝 **Responde a este mensaje con tu respuesta**\n"
                f"🔹 Solo se tomará en cuenta tu primera respuesta\n"
                f"🔹 ID de sesión: `{session_id}`"
            )
            enviados += 1
        except discord.Forbidden:
            errores.append(usuario.display_name)
        except Exception as e:
            errores.append(f"{usuario.display_name} (error: {str(e)})")
    
    # Responder con el estado inicial
    resultado = f"📊 **Poll iniciada en {canal_voz.name}**\n"
    resultado += f"❓ **Pregunta:** {pregunta}\n"
    resultado += f"⏰ **Tiempo límite:** {tiempo} segundos\n"
    resultado += f"👥 **Participantes:** {len(usuarios_conectados)}\n"
    resultado += f"✅ **Mensajes enviados:** {enviados}\n"
    
    if errores:
        resultado += f"❌ **No se pudo enviar a:** {', '.join(errores)}\n"
    
    resultado += f"\n🎭 **Las votaciones aparecerán automáticamente cuando termine el tiempo**"
    
    await ctx.send(resultado)
    
    # Programar el procesamiento automático de la poll
    await asyncio.sleep(tiempo)
    await procesar_poll(session_id)

# Ejecutar el bot
if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if token:
        bot.run(token)
    else:
        print('Error: No se encontró DISCORD_TOKEN en las variables de entorno')
        print('Asegúrate de tener un archivo .env con tu token de Discord')
