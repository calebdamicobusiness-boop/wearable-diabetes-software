"""Variables for the sensors when the sensor team lets us know what they are"""

GL =                            'something here from glucose monitoring'
HR =                            'something here from heart rate monitoring'
Accel =                         'accelerometer data'


from sensor_integration import IntegrationPipeline, SampleBuffer
from visualize import build_report

pipe = IntegrationPipeline(SampleBuffer("health_buffer.db"))
# ... register your sensors and call pipe.poll() as data comes in ...

build_report(pipe.buffer, {"glucose": "cgm", "hr": "hr"}, hours=6)



"""Bluetooth upload for App integration"""
