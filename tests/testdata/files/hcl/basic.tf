# Basic Terraform configuration
provider "aws" {
  region = "us-west-2"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

resource "aws_instance" "web" {
  ami           = "ami-12345678"
  instance_type = var.instance_type
  
  tags = {
    Name = "WebServer"
    Env  = "production"
  }
}

output "instance_ip" {
  value = aws_instance.web.public_ip
}
